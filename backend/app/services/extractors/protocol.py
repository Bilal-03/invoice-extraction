"""Shared contract for independently testable extraction families."""

from typing import Any, Protocol

from app.adapters.ocr.base import OCRResult


class Extractor(Protocol):
    """A field-family extractor with a stable OCR input boundary."""

    def extract(self, ocr_result: OCRResult) -> Any:
        """Extract one family of fields from an OCR result."""
