"""
config.py

Centralized application configuration, loaded from environment variables
(and a local `.env` file in development) via `pydantic-settings`.

Every other module (`db/session.py`, `client.py`, `worker.py`, `main.py`,
etc.) imports the single `settings` instance from here rather than reading
`os.environ` directly.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----------------------------------------------------------------- #
    # Database
    # ----------------------------------------------------------------- #

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/order_supervisor",
        description="Async SQLAlchemy database URL (asyncpg driver).",
    )
    db_echo: bool = Field(
        default=False,
        description="Echo SQL statements to the log (debug only).",
    )
    db_pool_size: int = Field(
        default=20,
        description="Base SQLAlchemy DB connection pool size.",
    )
    db_max_overflow: int = Field(
        default=20,
        description="Additional DB connections allowed above DB_POOL_SIZE.",
    )

    # ----------------------------------------------------------------- #
    # Temporal
    # ----------------------------------------------------------------- #

    temporal_target_host: str = Field(
        default="localhost:7233",
        description="Temporal server frontend address (host:port).",
    )
    temporal_namespace: str = Field(
        default="default",
        description="Temporal namespace to connect to.",
    )
    # Fix H3: this field used to be documented (README's .env example) as
    # the way to configure the task queue name, but nothing ever actually
    # read it — worker.py and api/routers/runs.py both import
    # shared.constants.TASK_QUEUE directly. Setting TASK_QUEUE_NAME in the
    # environment silently did nothing. shared/constants.py is intentionally
    # dependency-free (importable from inside the workflow sandbox) and is
    # kept as the single canonical source of truth for the task queue name,
    # so the dead duplicate field has been removed here rather than wired up.
    temporal_tls_enabled: bool = Field(
        default=False,
        description="Enable TLS when connecting to Temporal (required for Temporal Cloud).",
    )
    temporal_tls_client_cert: str | None = Field(
        default=None,
        description="PEM-encoded client certificate for Temporal Cloud mTLS.",
    )
    temporal_tls_client_key: str | None = Field(
        default=None,
        description="PEM-encoded client private key for Temporal Cloud mTLS.",
    )

    # ----------------------------------------------------------------- #
    # Worker tuning
    # ----------------------------------------------------------------- #

    worker_max_concurrent_activities: int = Field(
        default=40,
        description="Max activities the worker will execute concurrently.",
    )
    worker_max_concurrent_workflow_tasks: int = Field(
        default=100,
        description="Max workflow tasks the worker will process concurrently.",
    )

    # ----------------------------------------------------------------- #
    # API / CORS
    # ----------------------------------------------------------------- #

    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ],
        description=(
            "Allowed CORS origins for the FastAPI app. Use explicit origins "
            "when credentialed CORS is enabled."
        ),
    )


settings = Settings()
