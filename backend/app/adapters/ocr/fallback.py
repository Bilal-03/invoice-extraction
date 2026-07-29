"""OCR fallback chain that recovers from failures and low-confidence output."""

import numpy as np

from app.adapters.ocr.base import OCREngine, OCRResult
from app.core.logging import get_logger

logger = get_logger(__name__)


class FallbackOCREngine(OCREngine):
    def __init__(self, primary: OCREngine, fallback: OCREngine, threshold: float = 0.55):
        self.primary = primary
        self.fallback = fallback
        self.threshold = threshold

    @property
    def name(self) -> str:
        return f"{self.primary.name}->{self.fallback.name}"

    async def extract(self, image: np.ndarray) -> OCRResult:
        try:
            result = await self.primary.extract(image)
            if result.average_confidence >= self.threshold and result.raw_text.strip():
                return result
            logger.warning(
                "ocr_low_confidence_fallback",
                engine=self.primary.name,
                confidence=result.average_confidence,
            )
        except Exception as exc:
            logger.warning("ocr_engine_fallback", engine=self.primary.name, error=str(exc))
        return await self.fallback.extract(image)

    async def health_check(self) -> bool:
        return await self.primary.health_check() or await self.fallback.health_check()
