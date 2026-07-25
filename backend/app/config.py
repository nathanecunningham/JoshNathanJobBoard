"""Application settings, loaded from environment variables and backend/.env.

Everything here is optional at boot: the tracker works with no API keys
configured. AI and recommendation features check for their keys at call time.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str | None = None
    jsearch_api_key: str | None = None
    database_path: str = "backend-local.db"


def get_settings() -> Settings:
    """Read settings fresh from the environment / .env file."""
    return Settings()
