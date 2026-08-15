"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables or a .env file.
This centralises settings so nothing is hardcoded across the codebase.
"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.compat import StrEnum


class OCREngineType(StrEnum):
    """Supported OCR engine backends."""

    TESSERACT = "tesseract"
    PADDLEOCR = "paddleocr"
    PP_STRUCTURE_V3 = "pp-structure-v3"


class Environment(StrEnum):
    """Application environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class StorageBackend(StrEnum):
    LOCAL = "local"
    SUPABASE = "supabase"


class VLMProvider(StrEnum):
    """Supported local VLM providers."""

    NONE = "none"
    OLLAMA = "ollama"
    LLAMA_CPP = "llama.cpp"


class PipelineProfile(StrEnum):
    LOCAL_FULL = "local-full"
    DEMO_LITE = "demo-lite"


class DocumentParserType(StrEnum):
    """PDF/document structure parsers."""

    AUTO = "auto"
    DOCLING = "docling"
    PYMUPDF = "pymupdf"


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
    # Supabase Postgres is the only runtime database. The syntactically valid
    # placeholder keeps imports and isolated unit tests bootable; real runs
    # must provide DATABASE_URL in backend/.env or the deployment secret store.
    database_url: str = (
        "postgresql+asyncpg://postgres:password@db.invalid.supabase.co:5432/postgres"
    )

    # ── File Storage ─────────────────────────────────────────────────
    upload_dir: str = str(_BACKEND_ROOT / "data" / "uploads")
    # Supabase Storage is the only runtime file store. Tests can still inject
    # an in-memory storage adapter without changing application configuration.
    storage_backend: StorageBackend = StorageBackend.SUPABASE
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "documents"
    source_retention_days: int = 30
    max_file_size_mb: int = 20
    allowed_extensions: set[str] = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".pdf"}

    # ── OCR Engine ───────────────────────────────────────────────────
    pipeline_profile: PipelineProfile = PipelineProfile.LOCAL_FULL
    ocr_engine: OCREngineType = OCREngineType.PP_STRUCTURE_V3
    tesseract_cmd: str | None = None  # Auto-detect if None
    ocr_fallback_enabled: bool = True
    paddle_device: str = "cpu"
    document_parser: DocumentParserType = DocumentParserType.AUTO
    layout_engine: str = "pp-structure-v3"

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
    # Local Ollama is the zero-cost default; llama.cpp is an Intel-friendly
    # alternative. The deterministic OCR/rules path remains fully usable when
    # the local model server is not installed.
    vlm_enabled: bool = True
    vlm_provider: VLMProvider = VLMProvider.OLLAMA
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3-vl:2b"
    llama_cpp_base_url: str = "http://127.0.0.1:8080"
    llama_cpp_model: str = "local-model"
    vlm_confidence_threshold: float = 0.6  # Trigger VLM if overall confidence < this

    # ── Security ─────────────────────────────────────────────────────
    api_key: str | None = None  # If set, all endpoints require this key
    api_key_tenant_id: str = "local"
    auth_username: str | None = None
    auth_password: str | None = None
    jwt_secret: str | None = None
    jwt_expiry_minutes: int = 60
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
    ]
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
        """Prevent the application from silently using local persistence."""
        if self.pipeline_profile == PipelineProfile.DEMO_LITE:
            self.ocr_engine = OCREngineType.TESSERACT
            self.ocr_fallback_enabled = False
            self.vlm_enabled = False
            self.vlm_provider = VLMProvider.NONE
            self.document_parser = DocumentParserType.PYMUPDF
            self.layout_engine = "spatial-rules"
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the async PostgreSQL driver")
        database_host = urlparse(self.database_url).hostname or ""
        if "supabase" not in database_host.casefold():
            raise ValueError("DATABASE_URL must point to Supabase Postgres")
        if self.storage_backend != StorageBackend.SUPABASE:
            raise ValueError("STORAGE_BACKEND=supabase is required")
        return self


@lru_cache
def get_settings() -> Settings:
    """Factory function for dependency injection."""
    return Settings()
