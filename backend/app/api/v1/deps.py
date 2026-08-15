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
from app.adapters.storage.supabase_storage import SupabaseStorage
from app.adapters.vlm.base import VLMClient
from app.adapters.vlm.llama_cpp_client import LlamaCppVLMClient
from app.adapters.vlm.ollama_client import OllamaVLMClient
from app.core.config import (
    DocumentParserType,
    OCREngineType,
    PipelineProfile,
    Settings,
    StorageBackend,
    VLMProvider,
    get_settings,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Singletons for stateless adapters to avoid re-initializing on every request
_STORAGE_INSTANCE: ObjectStorage | None = None
_OCR_INSTANCE: OCREngine | None = None
_VLM_INSTANCE: VLMClient | None = None


def build_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend != StorageBackend.SUPABASE:
        raise RuntimeError("Supabase Storage is the only supported runtime file store")
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    return SupabaseStorage(
        settings.supabase_url,
        settings.supabase_service_role_key,
        settings.supabase_storage_bucket,
    )


def build_ocr_engine(settings: Settings) -> OCREngine:
    if settings.pipeline_profile == PipelineProfile.LOCAL_FULL or settings.ocr_engine in {
        OCREngineType.PADDLEOCR,
        OCREngineType.PP_STRUCTURE_V3,
    }:
        try:
            from app.adapters.ocr.paddle_structure import PaddleStructureV3OCREngine

            primary = PaddleStructureV3OCREngine(device=settings.paddle_device)
            if settings.ocr_fallback_enabled:
                from app.adapters.ocr.fallback import FallbackOCREngine

                return FallbackOCREngine(primary, TesseractOCR(settings.tesseract_cmd))
            return primary
        except Exception as exc:
            logger.warning("paddle_structure_fallback_to_tesseract", error=str(exc))

    return TesseractOCR(settings.tesseract_cmd)


def build_vlm_client(settings: Settings) -> VLMClient | None:
    if (
        settings.pipeline_profile == PipelineProfile.DEMO_LITE
        or not settings.vlm_enabled
        or settings.vlm_provider == VLMProvider.NONE
    ):
        return None
    if settings.vlm_provider == VLMProvider.OLLAMA:
        return OllamaVLMClient(settings.ollama_base_url, settings.ollama_model)
    if settings.vlm_provider == VLMProvider.LLAMA_CPP:
        return LlamaCppVLMClient(settings.llama_cpp_base_url, settings.llama_cpp_model)
    logger.warning("configured_vlm_provider_unavailable", provider=settings.vlm_provider.value)
    return None


def build_document_parser(settings: Settings):
    """Build the optional Docling parser, falling back to the PyMuPDF path."""
    if settings.document_parser == DocumentParserType.PYMUPDF:
        return None
    try:
        from app.adapters.parsing.docling_parser import DoclingDocumentParser

        return DoclingDocumentParser()
    except Exception as exc:
        if settings.document_parser == DocumentParserType.DOCLING:
            logger.warning("docling_unavailable_using_pymupdf", error=str(exc))
        else:
            logger.info("docling_not_installed_using_pymupdf", error=str(exc))
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
