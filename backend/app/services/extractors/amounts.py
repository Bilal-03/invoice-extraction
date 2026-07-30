"""Amounts, totals, taxes, and currency extraction family."""

from typing import Any

from app.adapters.ocr.base import OCRResult
from app.services.extractors.protocol import Extractor


class AmountExtractor(Extractor):
    """Owns financial extraction and delegates numeric parsing to the core matcher."""

    def __init__(self, legacy):
        self._legacy = legacy

    def extract(self, ocr_result: OCRResult) -> dict[str, Any]:
        text = ocr_result.raw_text
        words = ocr_result.words
        taxes = self._legacy._extract_taxes(text)
        subtotal = self._legacy._extract_amount(
            text,
            words,
            [
                "subtotal",
                "sub total",
                "sub-total",
                "amount before tax",
                "taxable amount",
                "net total",
            ],
        )
        return {
            "taxes": taxes,
            "subtotal": subtotal,
            "grand_total": self._legacy._extract_grand_total(text),
            "currency": self._legacy._detect_currency(text),
            "shipping_amount": self._legacy._extract_labeled_decimal(
                text, ["shipping charge", "shipping fee", "freight", "delivery charge"]
            ),
        }
