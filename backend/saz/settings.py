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
    PLANNER_MODEL: str = "gpt-4o"
    """The model used for planning tasks."""
    CRITIC_MODEL: str = "gpt-4o"
    """The model used for critiquing plans."""
    ALLOW_SENSITIVE_DATA: bool = False
    """Whether to allow exposing sensitive data (stack traces) via API.

    WARNING: Should ALWAYS be False in production.
    Only set to True in development/staging for debugging.
    """
    SUSPENSION_SWEEP_INTERVAL_SECONDS: float = 60.0
    """How often the SuspensionSweeper scans for timed-out suspended runs.

    Runs are suspended on human.approval and webhook.wait steps; the
    sweeper fails them once ``error.timeout_at`` has passed. Lower values
    make timeouts more responsive at the cost of DB load.
    """
    SUSPENSION_SWEEP_BATCH_LIMIT: int = 100
    """Maximum suspended-run rows processed in a single sweep pass."""
    SUSPENSION_SWEEP_ENABLED: bool = True
    """Disable the sweeper entirely (e.g. for in-process tests where the
    background thread would race with synchronous assertions)."""


settings = Settings()
