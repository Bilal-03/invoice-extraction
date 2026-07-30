"""
FastAPI Dependencies (Dependency Injection).

This is where the pluggable architecture is wired up. Endpoints request
an `OCREngine` or `ObjectStorage`, and this module provides the configured
implementation. This makes testing trivial (just override the dependency).
"""

from collections.abc import AsyncGenerator

from fastapi import Depends

from app.adapters.ocr.base import OCREngine
from app.adapters.ocr.tesseract_ocr import TesseractOCR
from app.adapters.storage.base import ObjectStorage
from app.adapters.storage.local_storage import LocalStorage
from app.adapters.storage.supabase_storage import SupabaseStorage
from app.adapters.vlm.base import VLMClient
from app.adapters.vlm.gemini_client import GeminiVLMClient
from app.core.config import OCREngineType, Settings, StorageBackend, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Singletons for stateless adapters to avoid re-initializing on every request
_STORAGE_INSTANCE: ObjectStorage | None = None
_OCR_INSTANCE: OCREngine | None = None
_VLM_INSTANCE: VLMClient | None = None


def build_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == StorageBackend.SUPABASE:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            if settings.environment.value == "development":
                logger.warning("supabase_storage_not_configured_using_explicit_dev_local_storage")
                return LocalStorage(base_dir=settings.upload_dir)
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        return SupabaseStorage(
            settings.supabase_url,
            settings.supabase_service_role_key,
            settings.supabase_storage_bucket,
        )
    return LocalStorage(base_dir=settings.upload_dir)


def build_ocr_engine(settings: Settings) -> OCREngine:
    if settings.ocr_engine == OCREngineType.PADDLEOCR:
        try:
            from app.adapters.ocr.paddle_ocr import PaddleOCREngine

            primary = PaddleOCREngine()
            if settings.ocr_fallback_enabled:
                from app.adapters.ocr.fallback import FallbackOCREngine

                return FallbackOCREngine(primary, TesseractOCR())
            return primary
        except (ImportError, RuntimeError):
            logger.warning("paddleocr_fallback_to_tesseract")
    return TesseractOCR()


def build_vlm_client(settings: Settings) -> VLMClient | None:
    if settings.vlm_enabled and settings.gemini_api_key:
        return GeminiVLMClient(api_key=settings.gemini_api_key, model=settings.vlm_model)
    if settings.vlm_enabled:
        logger.warning("vlm_enabled_but_no_api_key")
    return None


async def get_storage(
    settings: Settings = Depends(get_settings),
) -> AsyncGenerator[ObjectStorage, None]:
    """Dependency for object storage."""
    global _STORAGE_INSTANCE
    if _STORAGE_INSTANCE is None:
        _STORAGE_INSTANCE = build_storage(settings)
    yield _STORAGE_INSTANCE


async def get_ocr_engine(
    settings: Settings = Depends(get_settings),
) -> AsyncGenerator[OCREngine, None]:
    """Dependency for OCR engine."""
    global _OCR_INSTANCE
    if _OCR_INSTANCE is None:
        _OCR_INSTANCE = build_ocr_engine(settings)

    yield _OCR_INSTANCE


async def get_vlm_client(
    settings: Settings = Depends(get_settings),
) -> AsyncGenerator[VLMClient | None, None]:
    """Dependency for VLM fallback client (optional)."""
    global _VLM_INSTANCE
    if not settings.vlm_enabled:
        yield None
        return

    if _VLM_INSTANCE is None:
        _VLM_INSTANCE = build_vlm_client(settings)

    yield _VLM_INSTANCE
