"""Password hashing and secret comparison.

Interview notes:
- Argon2id (via pwdlib) is a memory-hard password hash: each guess costs an attacker
  ~64 MB of RAM and real CPU time, which makes GPU cracking expensive. Its salt and
  parameters are stored inside the hash string, so they can be raised later.
- Hashing takes ~90 ms on purpose. Running it directly in an async handler would block
  the event loop, so every other request would wait. It runs in a worker thread instead.
- Secrets (the invite code) are compared with hmac.compare_digest: it takes the same time
  however many leading characters match, so response timing can't leak the code.
- Session tokens are 256 random bits, so a fast hash (SHA-256) is enough to store them:
  nobody can guess-and-check 2^256 values. Passwords need a slow hash only because people
  choose guessable ones.
"""

import hashlib
import hmac
import secrets

from anyio import to_thread
from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()  # Argon2id with library-recommended parameters
_dummy_hash: str | None = None


def new_session_token() -> str:
    """256 bits from the OS's secure random source, URL-safe (43 characters)."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """What the DB stores. A DB leak alone gives no usable cookies."""
    return hashlib.sha256(token.encode()).hexdigest()


async def burn_password_check_time(password: str) -> None:
    """Spend the same time as a real check, for logins with an unknown email.

    Without it, "no such user" answers in ~1 ms and "wrong password" in ~90 ms, so response
    time would reveal which emails have accounts.
    """
    global _dummy_hash  # computed once, lazily: hashing at import time would slow startup
    if _dummy_hash is None:
        _dummy_hash = await hash_password(new_session_token())
    await verify_password(password, _dummy_hash)


async def hash_password(password: str) -> str:
    return await to_thread.run_sync(_password_hash.hash, password)


async def verify_password(password: str, password_hash: str) -> bool:
    return await to_thread.run_sync(_password_hash.verify, password, password_hash)


def secrets_match(given: str, expected: str) -> bool:
    """Constant-time comparison. Encoded to bytes so non-ASCII input can't raise."""
    return hmac.compare_digest(given.encode(), expected.encode())
