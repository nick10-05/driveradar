"""Auth endpoints: register, login, logout (DESIGN §7.3, §7.5, §8)."""

import math

import structlog
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import AppSettings, DbSession, Limiters
from app.core.config import Settings
from app.schemas.auth import LoginIn, RegisterIn, UserOut
from app.services.auth import (
    EmailAlreadyRegisteredError,
    InvalidInviteCodeError,
    authenticate,
    end_session,
    register_user,
    start_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger("app.security")

TOO_MANY = {"description": "Too many attempts (see Retry-After)"}


def client_ip(request: Request) -> str:
    # Behind Render's proxy, uvicorn --proxy-headers sets this from X-Forwarded-For.
    # It can be spoofed, which is why login's primary limit is per email.
    return request.client.host if request.client else "unknown"


def too_many_attempts(retry_after: float, limit_name: str) -> HTTPException:
    log.warning("rate_limited", limit=limit_name)  # no email/IP values in logs
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many attempts. Try again later.",
        headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
    )


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """HttpOnly: page JavaScript (and so an XSS payload) can't read the token.
    Secure: only sent over HTTPS. SameSite=Lax: not sent on cross-site POSTs (CSRF layer 1).
    Path=/ and no Domain: required by the "__Host-" prefix, so the cookie can't be set or
    overridden by a subdomain."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_403_FORBIDDEN: {"description": "Invalid invite code"},
        status.HTTP_409_CONFLICT: {"description": "Email already registered"},
        status.HTTP_429_TOO_MANY_REQUESTS: TOO_MANY,
    },
)
async def register(
    data: RegisterIn,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    limiters: Limiters,
) -> UserOut:
    ip = client_ip(request)
    if (retry_after := limiters.register_ip.hit(ip)) is not None:
        raise too_many_attempts(retry_after, "register_ip")
    try:
        user = await register_user(session, data, settings)
    except InvalidInviteCodeError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid invite code") from None
    except EmailAlreadyRegisteredError:
        limiters.register_ip.undo(ip)  # had the right invite code: not a guess
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from None
    # Only wrong invite codes count, so a whole class registering from one Wi-Fi is fine.
    limiters.register_ip.undo(ip)
    return UserOut.model_validate(user)


@router.post(
    "/login",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid email or password"},
        status.HTTP_429_TOO_MANY_REQUESTS: TOO_MANY,
    },
)
async def login(
    data: LoginIn,
    request: Request,
    response: Response,
    session: DbSession,
    settings: AppSettings,
    limiters: Limiters,
) -> UserOut:
    ip, email = client_ip(request), data.email.lower()
    # Count the attempt BEFORE the ~90 ms password check (see rate_limit.py).
    if (retry_after := limiters.login_ip.hit(ip)) is not None:
        raise too_many_attempts(retry_after, "login_ip")
    if (retry_after := limiters.login_email.hit(email)) is not None:
        limiters.login_ip.undo(ip)
        raise too_many_attempts(retry_after, "login_email")

    user = await authenticate(session, email, data.password.get_secret_value())
    if user is None:
        # One message for both cases: don't reveal whether the email has an account.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    # Success: failed attempts before it no longer count against this account or IP.
    limiters.login_email.reset(email)
    limiters.login_ip.undo(ip)

    # Logging in again from the same browser: drop the old session instead of orphaning it.
    if old_token := request.cookies.get(settings.session_cookie_name):
        await end_session(session, old_token)

    token = await start_session(session, user, settings)
    set_session_cookie(response, token, settings)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, session: DbSession, settings: AppSettings
) -> None:
    """Always 204, even without a valid session: the end state (logged out) is the same."""
    if token := request.cookies.get(settings.session_cookie_name):
        await end_session(session, token)
    clear_session_cookie(response, settings)
