"""Application settings: read once from env vars, validated, fail fast (DESIGN §7.2).

Interview notes:
- One frozen Settings object is built at startup. If anything is missing or invalid the app
  refuses to start and lists *every* problem, instead of crashing later on first use.
- Secrets (and the DB URL, which holds a password) are SecretStr, so they print as
  '**********' in logs, reprs and tracebacks. Error messages never echo input values.
"""

from contextlib import suppress
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_POSTGRES_DRIVERS = {"postgres", "postgresql", "postgresql+asyncpg"}
_SSL_REQUIRED_MODES = {"require", "verify-ca", "verify-full"}
# libpq-only parameters that asyncpg rejects as URL query params.
_LIBPQ_ONLY_PARAMS = ("sslmode", "channel_binding")


class ConfigError(Exception):
    """Raised at startup when the environment is missing or has invalid settings."""

    @classmethod
    def from_validation_error(cls, exc: ValidationError) -> "ConfigError":
        lines = []
        for error in exc.errors():
            name = str(error["loc"][0]).upper() if error["loc"] else "CONFIG"
            lines.append(f"  - {name}: {error['msg']}")  # never include error['input']
        return cls("Invalid configuration. Fix these environment variables:\n" + "\n".join(lines))


def normalize_database_url(raw: str) -> tuple[str, bool]:
    """Turn a libpq-style Postgres URL (as Neon gives it) into an asyncpg URL.

    Returns (url, ssl_required). `sslmode`/`channel_binding` are removed because asyncpg
    rejects them; SSL is instead passed to the driver in code (see app.core.db).
    """
    try:
        url = make_url(raw)
    except ArgumentError as exc:
        raise ValueError("must be a PostgreSQL URL like postgresql://user:pass@host/db") from exc

    if url.drivername not in _POSTGRES_DRIVERS:
        raise ValueError("must be a PostgreSQL URL like postgresql://user:pass@host/db")
    if url.host and "-pooler." in url.host:
        raise ValueError(
            "use Neon's direct host, not the '-pooler' host: PgBouncer in transaction mode "
            "breaks asyncpg's prepared statements"
        )

    query = dict(url.query)
    sslmode = query.get("sslmode")
    for param in _LIBPQ_ONLY_PARAMS:
        query.pop(param, None)

    normalized = url.set(drivername="postgresql+asyncpg", query=query)
    return normalized.render_as_string(hide_password=False), sslmode in _SSL_REQUIRED_MODES


class LlmSettings(BaseSettings):
    """Only the LLM_* variables (D10). The eval CLI loads just these; Settings extends it."""

    model_config = SettingsConfigDict(
        env_ignore_empty=True,  # `TELEGRAM_BOT_TOKEN=` in .env means "not set"
        extra="ignore",
        frozen=True,
    )

    llm_provider: Literal["none", "openai_compatible"] = "none"
    llm_base_url: HttpUrl | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_json_mode: Literal["schema", "object"] = "schema"
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)

    @model_validator(mode="after")
    def _llm_provider_needs_endpoint(self) -> Self:
        if self.llm_provider != "none" and (self.llm_base_url is None or not self.llm_model):
            raise ValueError(
                f"LLM_BASE_URL and LLM_MODEL must be set when LLM_PROVIDER={self.llm_provider}"
            )
        return self


class Settings(LlmSettings):
    environment: Literal["dev", "test", "prod"]

    database_url: SecretStr
    # Derived from DATABASE_URL's sslmode; not meant to be set directly.
    database_ssl: bool = False

    allowed_origins: Annotated[list[str], NoDecode]
    batch_invite_code: SecretStr = Field(min_length=8)
    cron_secret: SecretStr = Field(min_length=16)
    session_ttl_hours: int = Field(default=168, gt=0)
    # Only for browsers that refuse Secure cookies on http://localhost (e.g. Safari). Dev only.
    session_cookie_secure: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    telegram_bot_token: SecretStr | None = None
    telegram_webhook_secret: SecretStr | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_database_ssl(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("database_url"), str):
            # On a bad URL, the field validator below reports the error against DATABASE_URL.
            with suppress(ValueError):
                _, data["database_ssl"] = normalize_database_url(data["database_url"])
        return data

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: Any) -> Any:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            url, _ = normalize_database_url(value)
            return url
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, list):
            return value
        origins = [str(item).strip().rstrip("/") for item in value]
        origins = [origin for origin in origins if origin]
        if not origins:
            raise ValueError("needs at least one origin, e.g. http://localhost:5173")
        for origin in origins:
            parts = urlsplit(origin)
            if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path:
                raise ValueError(f"{origin!r} must be scheme://host[:port] with no path")
        return origins

    @property
    def session_cookie_name(self) -> str:
        # Browsers only accept a "__Host-" cookie if it is Secure, has Path=/ and no Domain,
        # so the prefix itself guarantees those flags. Without Secure, a plain name is needed.
        return "__Host-session" if self.session_cookie_secure else "session"

    @model_validator(mode="after")
    def _insecure_cookie_only_in_dev(self) -> Self:
        if not self.session_cookie_secure and self.environment != "dev":
            raise ValueError("SESSION_COOKIE_SECURE=false is only allowed when ENVIRONMENT=dev")
        return self


def load_config(env_file: str | None = ".env") -> Settings:
    """Build Settings from the environment (plus `env_file` for local dev), or fail fast.

    Tests pass env_file=None so a developer's local .env never leaks into them.
    """
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        raise ConfigError.from_validation_error(exc) from None
