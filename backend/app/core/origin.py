"""CSRF layer 2: unsafe requests must come from an allowed Origin (DESIGN §7.3).

Interview notes:
- Layer 1 is the cookie's SameSite=Lax: browsers don't attach it to cross-site POSTs.
  This check is the second layer, in case a browser bug or an old browser ignores it.
- Browsers always send `Origin` on POST/PUT/PATCH/DELETE, and page JavaScript can't fake
  it. So "Origin must be in ALLOWED_ORIGINS" means "the request came from our frontend".
- A missing Origin is rejected too (fail closed). Non-browser clients like curl don't
  send one, but they also don't carry a victim's cookies, so nothing useful is blocked.
- It covers login and register as well: that blocks "login CSRF", where an attacker
  silently logs the victim into the attacker's account.
- Machine endpoints (Telegram webhook, cron) authenticate with secret headers, not
  cookies, so CSRF doesn't apply and they are exempt.
"""

import json
from collections.abc import Iterable

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

log = structlog.get_logger("app.security")

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Secret-header endpoints (Day 8 / Day 9). Prefix match.
EXEMPT_PATH_PREFIXES: tuple[str, ...] = ("/telegram/webhook", "/internal/")

_FORBIDDEN_BODY = json.dumps({"detail": "Origin not allowed"}).encode()


class OriginCheckMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: Iterable[str],
        exempt_path_prefixes: tuple[str, ...] = EXEMPT_PATH_PREFIXES,
    ) -> None:
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)
        self.exempt_path_prefixes = exempt_path_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in UNSAFE_METHODS
            or scope["path"].startswith(self.exempt_path_prefixes)
        ):
            await self.app(scope, receive, send)
            return

        origin = _header(scope, b"origin")
        if origin in self.allowed_origins:
            await self.app(scope, receive, send)
            return

        # The origin is a public value (scheme://host), safe to log; it helps debug config.
        log.warning("origin_rejected", origin=origin, method=scope["method"], path=scope["path"])
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_FORBIDDEN_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _FORBIDDEN_BODY})


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return str(value.decode("latin-1"))
    return None
