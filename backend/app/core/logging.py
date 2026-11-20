"""Structured logging with structlog (DESIGN §7.5).

Interview notes:
- Every log line is one JSON object in prod (easy to search and filter in Render's log view),
  and readable console output in dev.
- structlog and the stdlib `logging` module share one pipeline, so uvicorn's own logs are
  JSON too and carry the same fields.
- Context variables (e.g. request_id) are merged into every line logged during a request.
- A redaction step replaces secret-looking values before anything is written.
"""

import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

from app.core.config import Settings

REDACTED = "[REDACTED]"

# Matched case-insensitively against the *end* of a key, e.g. "llm_api_key", "X-Auth-Token".
_SENSITIVE_SUFFIXES = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "set-cookie",
    "session",
    "invite_code",
    "database_url",
)
_NORMALIZED_SUFFIXES = tuple(s.replace("-", "_") for s in _SENSITIVE_SUFFIXES)


class _CurrentStdout:
    """Writes to whatever sys.stdout is at call time, so redirection (and pytest capture)
    keeps working even after logging was configured."""

    def write(self, text: str) -> int:
        return sys.stdout.write(text)

    def flush(self) -> None:
        sys.stdout.flush()


def _is_sensitive(key: str) -> bool:
    return key.lower().replace("-", "_").endswith(_NORMALIZED_SUFFIXES)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: REDACTED if _is_sensitive(str(k)) else _redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


def redact_sensitive(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for key in list(event_dict):
        if _is_sensitive(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging. Safe to call more than once (tests do)."""
    level = getattr(logging, settings.log_level)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    renderer: Processor
    if settings.environment == "dev":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Not caching keeps reconfiguration (tests, reloads) reliable; the cost is negligible here.
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[*shared, structlog.processors.format_exc_info],
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(_CurrentStdout())
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Let uvicorn's loggers flow to the root handler. Our middleware writes the access log.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs every request URL at INFO, and Telegram's Bot API puts the bot token in
    # the URL (/bot<token>/sendMessage). WARNING keeps the token out of the logs.
    # httpx2/httpcore2 arrive via fastapi[standard]; silenced too, in case code moves to them.
    for name in ("httpx", "httpcore", "httpx2", "httpcore2"):
        logging.getLogger(name).setLevel(logging.WARNING)
