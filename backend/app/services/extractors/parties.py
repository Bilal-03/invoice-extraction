"""Vendor and buyer extraction family."""

from typing import Any

from app.adapters.ocr.base import OCRResult
from app.services.extractors.protocol import Extractor


class PartyExtractor(Extractor):
    """Owns vendor/buyer sections and their spatial column policy."""

    def __init__(self, legacy):
        self._legacy = legacy

    def extract(self, ocr_result: OCRResult) -> dict[str, Any]:
        return {
            "vendor": self._legacy._extract_vendor(
                ocr_result.raw_text, ocr_result.words, ocr_result.lines()
            ),
            "buyer": self._legacy._extract_buyer(ocr_result.raw_text, ocr_result.lines()),
        }
