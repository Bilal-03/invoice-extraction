"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables or a .env file.
This centralises settings so nothing is hardcoded across the codebase.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OCREngineType(StrEnum):
    """Supported OCR engine backends."""

    TESSERACT = "tesseract"
    PADDLEOCR = "paddleocr"


class Environment(StrEnum):
    """Application environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class StorageBackend(StrEnum):
    LOCAL = "local"
    SUPABASE = "supabase"


# Resolve project root relative to this file
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """
    Central configuration. Values are read from environment variables
    (case-insensitive) or a .env file at the backend root.
    """

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────
    app_name: str = "Invoice Intelligence Platform"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_version: str = "v1"
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Database ─────────────────────────────────────────────────────
    # SQLite remains deliberately available for a laptop-only development setup.
    # Every shared environment must use the durable Postgres queue.
    database_url: str = f"sqlite+aiosqlite:///{_BACKEND_ROOT / 'data' / 'invoices.db'}"

    # ── File Storage ─────────────────────────────────────────────────
    upload_dir: str = str(_BACKEND_ROOT / "data" / "uploads")
    # Hosted object storage is the safe default; local must be explicitly opted
    # into in a development .env file.
    storage_backend: StorageBackend = StorageBackend.SUPABASE
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "documents"
    source_retention_days: int = 30
    max_file_size_mb: int = 20
    allowed_extensions: set[str] = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".pdf"}

    # ── OCR Engine ───────────────────────────────────────────────────
    ocr_engine: OCREngineType = OCREngineType.TESSERACT
    tesseract_cmd: str | None = None  # Auto-detect if None
    ocr_fallback_enabled: bool = True

    # ── Preprocessing ────────────────────────────────────────────────
    preprocessing_deskew: bool = True
    preprocessing_denoise: bool = True
    preprocessing_orient: bool = True
    pipeline_max_concurrency: int = 2
    pdf_render_dpi: int = 160
    worker_poll_interval_seconds: float = 2.0
    worker_max_attempts: int = 3
    # Workers are a separate process by default; never run OCR in API request workers.
    embedded_worker_enabled: bool = False

    # ── VLM Fallback ─────────────────────────────────────────────────
    # Verification is always attempted when a server-side key is configured.
    vlm_enabled: bool = True
    gemini_api_key: str | None = None
    vlm_confidence_threshold: float = 0.6  # Trigger VLM if overall confidence < this
    # Pin a stable, high-throughput multimodal model rather than a mutable alias.
    vlm_model: str = "gemini-3.5-flash-lite"
    vlm_input_cost_per_million: float = 0.0
    vlm_output_cost_per_million: float = 0.0

    # ── Security ─────────────────────────────────────────────────────
    api_key: str | None = None  # If set, all endpoints require this key
    api_key_tenant_id: str = "local"
    auth_username: str | None = None
    auth_password: str | None = None
    jwt_secret: str | None = None
    jwt_expiry_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    rate_limit: str = "60/minute"
    clamav_enabled: bool = False
    clamav_command: str = "clamscan"

    # ── Logging ──────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_json: bool = False  # Set True in production

    # ── Distributed tracing ─────────────────────────────────────────
    tracing_enabled: bool = True
    tracing_service_name: str = "invoice-intelligence-api"
    tracing_otlp_endpoint: str | None = None
    tracing_sample_rate: float = 1.0

    @model_validator(mode="after")
    def require_durable_shared_services(self) -> "Settings":
        """Prevent a deploy from silently using single-host development services."""
        if self.environment != Environment.DEVELOPMENT:
            if self.database_url.startswith("sqlite"):
                raise ValueError("DATABASE_URL must point to Postgres outside development")
            if self.storage_backend != StorageBackend.SUPABASE:
                raise ValueError("STORAGE_BACKEND=supabase is required outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    """Factory function for dependency injection."""
    return Settings()
