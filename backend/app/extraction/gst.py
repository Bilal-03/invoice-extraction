"""GSTIN extraction, normalisation, and local syntax validation."""

from __future__ import annotations

import re

from app.adapters.ocr.base import OCRResult
from app.domain.schemas import FieldValue
from app.extraction.context import RuleContext

# GSTIN: state (2) + PAN (10) + entity (1) + literal Z (1) + checksum (1).
GSTIN_PATTERN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z0-9]", re.IGNORECASE)
GSTIN_CANDIDATE_PATTERN = re.compile(r"(?<![A-Z0-9])([0-9A-Z]{15})(?![A-Z0-9])", re.IGNORECASE)
GSTIN_LABELS = (
    "gstin",
    "gstin no",
    "gstin number",
    "gst no",
    "gst number",
    "gst registration number",
    "gst registration no",
    "gst registration",
    "tax registration number",
)


def normalize_gstin(value: str) -> str:
    """Normalise OCR GSTIN text without making a government verification claim."""

    candidate = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    chars = list(candidate)
    # Common OCR substitutions in the numeric GSTIN positions.  We preserve
    # all other characters so an invalid candidate remains visible to review.
    for index in (0, 1, 7, 8, 9, 10, 12):
        if index < len(chars):
            chars[index] = {"O": "0", "I": "1", "L": "1"}.get(chars[index], chars[index])
    return "".join(chars)


def is_valid_gstin_syntax(value: str | None) -> bool:
    """Validate the local 15-character GSTIN shape only; no network/API call."""

    return bool(value and GSTIN_PATTERN.fullmatch(value.strip().upper()))


def extract_gstin(result: OCRResult) -> FieldValue | None:
    """Extract and uppercase the first label-near or document-level GSTIN."""

    context = RuleContext(result)
    match = context.find_labeled_value(GSTIN_LABELS, GSTIN_CANDIDATE_PATTERN)
    if match is None:
        match = context.find_text(GSTIN_CANDIDATE_PATTERN)
    if match is None:
        return None

    value = normalize_gstin(match.value)
    if len(value) != 15:
        return None
    syntax_confidence = 0.96 if is_valid_gstin_syntax(value) else 0.72
    confidence = min(0.99, max(syntax_confidence, match.confidence))
    return context.field_value(value, confidence, page=match.page, words=match.words)
