"""Password hashing and constant-time secret comparison (no DB needed)."""

import pytest

from app.core.security import hash_password, secrets_match, verify_password

pytestmark = pytest.mark.anyio


async def test_hash_is_argon2id_and_never_the_password() -> None:
    hashed = await hash_password("correct horse battery")

    assert hashed.startswith("$argon2id$")
    assert "correct horse battery" not in hashed


async def test_same_password_gives_different_hashes() -> None:
    # A random salt per hash: equal passwords can't be spotted in a DB dump.
    assert await hash_password("same password") != await hash_password("same password")


async def test_verify_accepts_right_password_and_rejects_wrong_one() -> None:
    hashed = await hash_password("correct horse battery")

    assert await verify_password("correct horse battery", hashed) is True
    assert await verify_password("Correct horse battery", hashed) is False


@pytest.mark.parametrize(
    ("given", "expected", "result"),
    [
        ("invite-code-123", "invite-code-123", True),
        ("invite-code-124", "invite-code-123", False),
        ("invite-code-12", "invite-code-123", False),
        ("", "invite-code-123", False),
        ("ïnvite-code-123", "invite-code-123", False),  # non-ASCII must not raise
    ],
)
def test_secrets_match(given: str, expected: str, result: bool) -> None:
    assert secrets_match(given, expected) is result
