"""Backward-compatible import for the recommended PaddleOCR adapter."""

from app.adapters.ocr.paddle_structure import (
    PADDLE_AVAILABLE,
)
from app.adapters.ocr.paddle_structure import (
    PaddleStructureV3OCREngine as PaddleOCREngine,
)

__all__ = ["PADDLE_AVAILABLE", "PaddleOCREngine"]
