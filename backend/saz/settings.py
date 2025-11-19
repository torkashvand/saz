import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """General parameters for a GSO configuration file."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite:///./saz.db"
    """The database connection URL."""
    OPENAI_API_KEY: str = ""
    """The API key for accessing OpenAI services."""
    CREDENTIALS_ENCRYPTION_KEY: str = ""
    """The encryption key used for securing credentials."""
    LLM_MODEL: str = "gpt-4o-mini"
    """The default language model to use for LLM operations."""


settings = Settings()
