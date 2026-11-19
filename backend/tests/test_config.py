"""load_config(): read env vars, validate them, fail fast with a clear message."""

from typing import ClassVar

import pytest

from app.core.config import ConfigError, load_config, normalize_database_url


class TestLoadConfig:
    def test_minimal_valid_env_loads_with_defaults(self, valid_env: pytest.MonkeyPatch) -> None:
        settings = load_config(env_file=None)

        assert settings.environment == "test"
        assert settings.session_ttl_hours == 168
        assert settings.llm_provider == "none"  # ₹0 default: manual entry
        assert settings.log_level == "INFO"
        assert settings.allowed_origins == ["http://localhost:5173"]

    @pytest.mark.parametrize(
        "missing", ["ENVIRONMENT", "DATABASE_URL", "ALLOWED_ORIGINS", "BATCH_INVITE_CODE"]
    )
    def test_missing_required_var_fails_and_names_it(
        self, valid_env: pytest.MonkeyPatch, missing: str
    ) -> None:
        valid_env.delenv(missing)

        with pytest.raises(ConfigError, match=missing):
            load_config(env_file=None)

    def test_reports_every_problem_at_once(self, clean_env: pytest.MonkeyPatch) -> None:
        with pytest.raises(ConfigError) as exc_info:
            load_config(env_file=None)

        message = str(exc_info.value)
        for name in ("ENVIRONMENT", "DATABASE_URL", "BATCH_INVITE_CODE", "CRON_SECRET"):
            assert name in message

    def test_invalid_environment_value_is_rejected(self, valid_env: pytest.MonkeyPatch) -> None:
        valid_env.setenv("ENVIRONMENT", "staging")

        with pytest.raises(ConfigError, match="ENVIRONMENT"):
            load_config(env_file=None)

    @pytest.mark.parametrize(
        ("name", "value"), [("BATCH_INVITE_CODE", "short"), ("CRON_SECRET", "x" * 15)]
    )
    def test_secrets_that_are_too_short_are_rejected(
        self, valid_env: pytest.MonkeyPatch, name: str, value: str
    ) -> None:
        valid_env.setenv(name, value)

        with pytest.raises(ConfigError, match=name):
            load_config(env_file=None)

    def test_secrets_are_hidden_in_repr(self, valid_env: pytest.MonkeyPatch) -> None:
        settings = load_config(env_file=None)

        text = repr(settings)
        assert "invite-code-123" not in text
        assert "cron-secret-0123456789" not in text
        assert settings.batch_invite_code.get_secret_value() == "invite-code-123"

    def test_empty_optional_vars_count_as_unset(self, valid_env: pytest.MonkeyPatch) -> None:
        valid_env.setenv("TELEGRAM_BOT_TOKEN", "")
        valid_env.setenv("LLM_BASE_URL", "")

        settings = load_config(env_file=None)

        assert settings.telegram_bot_token is None
        assert settings.llm_base_url is None

    def test_session_ttl_must_be_positive(self, valid_env: pytest.MonkeyPatch) -> None:
        valid_env.setenv("SESSION_TTL_HOURS", "0")

        with pytest.raises(ConfigError, match="SESSION_TTL_HOURS"):
            load_config(env_file=None)


class TestSessionCookie:
    def test_secure_host_cookie_by_default(self, valid_env: pytest.MonkeyPatch) -> None:
        settings = load_config(env_file=None)

        assert settings.session_cookie_secure is True
        assert settings.session_cookie_name == "__Host-session"

    def test_insecure_cookie_allowed_in_dev_with_plain_name(
        self, valid_env: pytest.MonkeyPatch
    ) -> None:
        valid_env.setenv("ENVIRONMENT", "dev")
        valid_env.setenv("SESSION_COOKIE_SECURE", "false")

        settings = load_config(env_file=None)

        assert settings.session_cookie_name == "session"  # "__Host-" requires Secure

    @pytest.mark.parametrize("environment", ["test", "prod"])
    def test_insecure_cookie_rejected_outside_dev(
        self, valid_env: pytest.MonkeyPatch, environment: str
    ) -> None:
        valid_env.setenv("ENVIRONMENT", environment)
        valid_env.setenv("SESSION_COOKIE_SECURE", "false")

        with pytest.raises(ConfigError, match="SESSION_COOKIE_SECURE"):
            load_config(env_file=None)


class TestAllowedOrigins:
    def test_comma_separated_list_is_split_and_trimmed(self, valid_env: pytest.MonkeyPatch) -> None:
        valid_env.setenv(
            "ALLOWED_ORIGINS", " https://driveradar.vercel.app/ , http://localhost:5173 "
        )

        settings = load_config(env_file=None)

        assert settings.allowed_origins == [
            "https://driveradar.vercel.app",
            "http://localhost:5173",
        ]

    @pytest.mark.parametrize(
        "origin", ["driveradar.vercel.app", "ftp://x.com", "https://x.com/path"]
    )
    def test_origin_must_be_scheme_and_host_only(
        self, valid_env: pytest.MonkeyPatch, origin: str
    ) -> None:
        valid_env.setenv("ALLOWED_ORIGINS", origin)

        with pytest.raises(ConfigError, match="ALLOWED_ORIGINS"):
            load_config(env_file=None)

    def test_empty_list_is_rejected(self, valid_env: pytest.MonkeyPatch) -> None:
        valid_env.setenv("ALLOWED_ORIGINS", " , ")

        with pytest.raises(ConfigError, match="ALLOWED_ORIGINS"):
            load_config(env_file=None)


class TestLlmSettings:
    def test_openai_compatible_requires_base_url_and_model(
        self, valid_env: pytest.MonkeyPatch
    ) -> None:
        valid_env.setenv("LLM_PROVIDER", "openai_compatible")

        with pytest.raises(ConfigError, match="LLM_BASE_URL") as exc_info:
            load_config(env_file=None)
        assert "LLM_MODEL" in str(exc_info.value)

    def test_openai_compatible_with_base_url_and_model_loads(
        self, valid_env: pytest.MonkeyPatch
    ) -> None:
        valid_env.setenv("LLM_PROVIDER", "openai_compatible")
        valid_env.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
        valid_env.setenv("LLM_MODEL", "some-local-model")

        settings = load_config(env_file=None)

        assert settings.llm_model == "some-local-model"
        assert settings.llm_api_key is None  # local servers may need no key

    def test_unknown_provider_is_rejected(self, valid_env: pytest.MonkeyPatch) -> None:
        valid_env.setenv("LLM_PROVIDER", "magic")

        with pytest.raises(ConfigError, match="LLM_PROVIDER"):
            load_config(env_file=None)


class TestNormalizeDatabaseUrl:
    """Neon gives libpq-style URLs; asyncpg needs a different shape (DESIGN §7.4)."""

    def test_plain_postgresql_url_gets_asyncpg_driver(self) -> None:
        url, ssl = normalize_database_url("postgresql://u:p@localhost:5432/db")

        assert url == "postgresql+asyncpg://u:p@localhost:5432/db"
        assert ssl is False

    def test_postgres_alias_scheme_is_accepted(self) -> None:
        url, _ = normalize_database_url("postgres://u:p@localhost/db")

        assert url.startswith("postgresql+asyncpg://")

    def test_neon_ssl_params_are_removed_and_ssl_is_required(self) -> None:
        raw = (
            "postgresql://u:p@ep-cool-123.ap-southeast-1.aws.neon.tech/neondb"
            "?sslmode=require&channel_binding=require"
        )

        url, ssl = normalize_database_url(raw)

        assert url == "postgresql+asyncpg://u:p@ep-cool-123.ap-southeast-1.aws.neon.tech/neondb"
        assert ssl is True

    def test_other_query_params_are_kept(self) -> None:
        url, _ = normalize_database_url("postgresql://u:p@h/db?sslmode=disable&application_name=dr")

        assert url == "postgresql+asyncpg://u:p@h/db?application_name=dr"

    def test_special_characters_in_password_survive(self) -> None:
        url, _ = normalize_database_url("postgresql://u:p%40ss%2Fw@h/db")

        assert url == "postgresql+asyncpg://u:p%40ss%2Fw@h/db"

    @pytest.mark.parametrize("raw", ["mysql://u:p@h/db", "sqlite:///x.db", "not a url"])
    def test_non_postgres_urls_are_rejected(self, raw: str) -> None:
        with pytest.raises(ValueError, match="PostgreSQL"):
            normalize_database_url(raw)

    def test_pooler_host_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="pooler"):
            normalize_database_url("postgresql://u:p@ep-cool-123-pooler.neon.tech/neondb")

    def test_load_config_stores_normalised_url(self, valid_env: pytest.MonkeyPatch) -> None:
        valid_env.setenv("DATABASE_URL", "postgres://u:p@h.neon.tech/db?sslmode=require")

        settings = load_config(env_file=None)

        assert settings.database_url.get_secret_value() == "postgresql+asyncpg://u:p@h.neon.tech/db"
        assert settings.database_ssl is True
        assert "u:p@" not in repr(settings)  # the URL contains a password


class TestTelegramConfig:
    TELEGRAM: ClassVar[dict[str, str]] = {
        "TELEGRAM_BOT_TOKEN": "123456:fake-token",
        "TELEGRAM_WEBHOOK_SECRET": "webhook-secret-0123456789",
        "TELEGRAM_BOT_USERNAME": "DriveRadarBot",
    }

    def test_off_by_default(self, valid_env: pytest.MonkeyPatch) -> None:
        settings = load_config(env_file=None)

        assert settings.telegram_enabled is False

    def test_all_three_turn_it_on(self, valid_env: pytest.MonkeyPatch) -> None:
        for key, value in self.TELEGRAM.items():
            valid_env.setenv(key, value)

        settings = load_config(env_file=None)

        assert settings.telegram_enabled is True
        assert "fake-token" not in repr(settings)  # SecretStr

    @pytest.mark.parametrize("missing", list(TELEGRAM))
    def test_partial_config_fails(self, valid_env: pytest.MonkeyPatch, missing: str) -> None:
        for key, value in self.TELEGRAM.items():
            if key != missing:
                valid_env.setenv(key, value)

        with pytest.raises(ConfigError, match="must be set together"):
            load_config(env_file=None)

    @pytest.mark.parametrize("secret", ["short", "has spaces in it!!", "x" * 257])
    def test_webhook_secret_must_be_telegram_safe(
        self, valid_env: pytest.MonkeyPatch, secret: str
    ) -> None:
        for key, value in self.TELEGRAM.items():
            valid_env.setenv(key, value)
        valid_env.setenv("TELEGRAM_WEBHOOK_SECRET", secret)

        with pytest.raises(ConfigError) as exc_info:
            load_config(env_file=None)

        assert "TELEGRAM_WEBHOOK_SECRET" in str(exc_info.value)
        assert secret not in str(exc_info.value)  # never echo a secret

    def test_bot_username_is_validated(self, valid_env: pytest.MonkeyPatch) -> None:
        for key, value in self.TELEGRAM.items():
            valid_env.setenv(key, value)
        valid_env.setenv("TELEGRAM_BOT_USERNAME", "@bad name")

        with pytest.raises(ConfigError, match="TELEGRAM_BOT_USERNAME"):
            load_config(env_file=None)
