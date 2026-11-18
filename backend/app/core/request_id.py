"""Request-ID middleware + one structured access-log line per request (DESIGN §7.5).

Interview notes:
- Pure ASGI middleware (not Starlette's BaseHTTPMiddleware): no extra task per request, and
  the request_id context variable is visible to every log call made while handling it.
- An incoming X-Request-ID (e.g. from a proxy) is reused only if it is short and safe;
  anything else is replaced, so clients can't inject text into our logs or headers.
- The query string is never logged: it can contain tokens.
"""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_QUIET_PATHS = frozenset({"/healthz", "/readyz"})  # uptime probes log at DEBUG

log = structlog.get_logger("app.request")


def _request_id_from(scope: Scope) -> str:
    incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if incoming and _SAFE_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from(scope)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500  # if the app crashes before sending a response
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            log.exception("request_failed")
            raise
        finally:
            path = scope["path"]
            log_method = log.debug if path in _QUIET_PATHS else log.info
            log_method(
                "request",
                method=scope["method"],
                path=path,
                status_code=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()
