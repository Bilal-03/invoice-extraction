"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables or a .env file.
This centralises settings so nothing is hardcoded across the codebase.
"""

from enum import StrEnum
from pathlib import Path

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
    database_url: str = f"sqlite+aiosqlite:///{_BACKEND_ROOT / 'data' / 'invoices.db'}"

    # ── File Storage ─────────────────────────────────────────────────
    upload_dir: str = str(_BACKEND_ROOT / "data" / "uploads")
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

    # ── VLM Fallback ─────────────────────────────────────────────────
    vlm_enabled: bool = False
    gemini_api_key: str | None = None
    vlm_confidence_threshold: float = 0.6  # Trigger VLM if overall confidence < this
    vlm_model: str = "gemini-2.5-flash"
    vlm_input_cost_per_million: float = 0.0
    vlm_output_cost_per_million: float = 0.0

    # ── Security ─────────────────────────────────────────────────────
    api_key: str | None = None  # If set, all endpoints require this key
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


def get_settings() -> Settings:
    """Factory function for dependency injection."""
    return Settings()
