import logging
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    ARTIFACT_STORAGE_PATH: str = "./data/artifacts"
    """Directory where run artifacts (rendered documents, audit records) are stored.

    Defaults to a persistent, app-relative ``./data/artifacts`` rather than an
    ephemeral ``/tmp`` location so downloads survive restarts. Override via the
    ``ARTIFACT_STORAGE_PATH`` env var (e.g. an absolute path or a mounted volume).
    """
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
    AUTO_APPROVAL_BRIEFS_ENABLED: bool = True
    """Auto-generate an AI approval brief when a human.approval gate is reached.

    Enabled by default so every approval screen is understandable without a
    manual summary step. A workflow can opt a step out via the approval params
    (``approval_brief: false``). Generation never blocks the gate: on LLM
    failure a deterministic fallback brief is stored instead."""

    # --- Authentication ---
    JWT_SECRET_KEY: str = ""
    """HMAC secret used to sign and verify JWT access tokens.

    Production deployments MUST set this to a strong random value.
    A blank value disables auth-token issuance (login will fail) so an
    unconfigured deployment fails closed rather than minting tokens
    anyone with the source code could forge.
    """
    JWT_ALGORITHM: str = "HS256"
    """JWT signing algorithm. HS256 (HMAC-SHA256) is the default; do not
    change without also rotating ``JWT_SECRET_KEY`` and reviewing the
    decode path."""
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    """Access-token lifetime in minutes. Refresh tokens and revocation are
    out of scope — when this expires the user must log in again."""

    # --- CORS ---
    # ``NoDecode`` keeps pydantic-settings from JSON-parsing the env value,
    # so the validator below sees the raw ``"a,b,c"`` string and can split
    # on commas without first tripping a JSONDecodeError.
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    """Browser origins permitted to call the API.
    ``ALLOWED_ORIGINS=https://app.example.com,https://staging.example.com``.
    """

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _parse_allowed_origins(cls, value: object) -> object:
        """Accept ``a,b,c`` in env vars in addition to a real list.

        Pydantic-settings would otherwise demand JSON (``["a","b"]``),
        which is awkward to type into ``.env``. A literal list passed
        in code (the default, or by tests) flows through unchanged.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
