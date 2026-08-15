"""Amount, tax, total, currency, and shipping rule family."""

from __future__ import annotations

from typing import Any

from app.adapters.ocr.base import OCRResult


def extract_amounts(result: OCRResult, legacy_extractor: Any) -> dict[str, Any]:
    """Expose the tested numeric matchers behind a dedicated rule boundary."""

    text = result.raw_text
    words = result.words
    taxes = legacy_extractor._extract_taxes(text)
    subtotal = legacy_extractor._extract_amount(
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
        "grand_total": legacy_extractor._extract_grand_total(text),
        "currency": legacy_extractor._detect_currency(text),
        "shipping_amount": legacy_extractor._extract_labeled_decimal(
            text, ["shipping charge", "shipping fee", "freight", "delivery charge"]
        ),
    }
