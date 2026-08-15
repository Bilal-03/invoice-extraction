"""PaddleOCR/PP-StructureV3 service imports.

The implementation lives in the adapter layer so the Docker/local-full
profile can be optional.  Keeping this facade makes the intended service
boundary explicit and preserves one provider implementation.
"""

from app.adapters.ocr.paddle_ocr import PADDLE_AVAILABLE, PaddleOCREngine
from app.adapters.ocr.paddle_structure import (
    PaddleStructureV3OCREngine,
    normalise_paddle_result,
)

__all__ = [
    "PADDLE_AVAILABLE",
    "PaddleOCREngine",
    "PaddleStructureV3OCREngine",
    "normalise_paddle_result",
]
