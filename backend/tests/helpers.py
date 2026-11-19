"""Small helpers shared by test modules (fixtures live in conftest.py)."""

from pydantic import SecretStr

from app.core.config import Settings, normalize_database_url


def with_database_url(settings: Settings, raw_url: str) -> Settings:
    """A copy of settings pointing at another database (same normalisation as load_config)."""
    url, ssl = normalize_database_url(raw_url)
    return settings.model_copy(update={"database_url": SecretStr(url), "database_ssl": ssl})
