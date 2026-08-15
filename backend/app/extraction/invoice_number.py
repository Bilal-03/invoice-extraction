"""Deterministic invoice-number extraction rules."""

from __future__ import annotations

import re

from app.adapters.ocr.base import OCRResult
from app.domain.schemas import ExtractionSource, FieldValue
from app.extraction.context import RuleContext

INVOICE_NUMBER_LABELS = (
    "tax invoice number",
    "tax invoice no",
    "invoice number",
    "invoice no",
    "invoice #",
    "inv number",
    "inv no",
    "bill number",
    "bill no",
    "reference number",
    "reference no",
    "ref number",
    "ref no",
)

VALUE_PATTERN = re.compile(r"(?<![A-Z0-9])([A-Z0-9][A-Z0-9._/\-]{2,})(?![A-Z0-9])", re.IGNORECASE)


def extract_invoice_number(result: OCRResult) -> FieldValue:
    """Extract an invoice number from a nearby label, then use safe fallbacks."""

    context = RuleContext(result)
    match = context.find_labeled_value(INVOICE_NUMBER_LABELS, VALUE_PATTERN)
    if match is None:
        match = context.find_text(
            re.compile(
                r"(?:tax\s+invoice|invoice|inv|bill|reference|ref)\s*"
                r"(?:number|num|no\.?|#)?\s*[:#\-.]?\s*"
                r"([A-Z0-9][A-Z0-9._/\-]{2,})",
                re.IGNORECASE,
            )
        )
    if match is None:
        match = context.find_text(re.compile(r"\b([A-Z]{2,4}[-/]\d{4,}[-/]?\d*)\b", re.IGNORECASE))
    if match is None:
        return FieldValue(value=None, confidence=0.0, source=ExtractionSource.OCR_RULE)

    value = match.value.strip(" .:;,#")
    confidence = min(0.99, max(0.78, match.confidence + 0.12))
    return context.field_value(value, confidence, page=match.page, words=match.words)
