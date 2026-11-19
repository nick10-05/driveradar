"""Request/response models for auth.

Interview notes:
- extra="forbid": a client can't sneak in fields like {"role": "admin"}. Unknown fields
  are a 422, not silently ignored, so mass-assignment bugs can't happen later either.
- Password and invite code are SecretStr: if a model is ever printed or logged, they
  show as '**********'.
- Password rules follow NIST SP 800-63B: a minimum length and no composition rules
  ("one symbol, one digit..."), which mostly produce predictable passwords. The maximum
  (128) stops someone from sending a 10 MB password to make hashing expensive.
"""

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, StringConstraints

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: Annotated[
        SecretStr, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    ]
    name: Name
    invite_code: SecretStr

    def normalized_email(self) -> str:
        """Emails are stored lower-cased (the DB enforces it), so 'A@x.com' == 'a@x.com'."""
        return self.email.lower()


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    # No minimum here (old accounts must still log in if the rules change); the maximum
    # still caps how much work one login request can cause.
    password: Annotated[SecretStr, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: str
