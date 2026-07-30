"""Date extraction family."""

from typing import Any

from app.adapters.ocr.base import OCRResult
from app.services.extractors.protocol import Extractor


class DateExtractor(Extractor):
    """Owns invoice and due-date policy while reusing the battle-tested matcher."""

    def __init__(self, legacy):
        self._legacy = legacy

    def extract(self, ocr_result: OCRResult) -> dict[str, Any]:
        text = ocr_result.raw_text
        words = ocr_result.words
        return {
            "invoice_date": self._legacy._extract_date(
                text,
                words,
                ["invoice date", "inv date", "date of invoice", "billing date", "invoice dt", "dated", "date:"],
            ),
            "due_date": self._legacy._extract_date(
                text,
                words,
                ["due date", "payment due", "due by", "pay by", "due on", "payment date", "due dt"],
                allow_fallback=False,
            ),
        }
