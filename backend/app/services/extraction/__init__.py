"""Rule-first extraction service boundary."""

from app.services.extraction.rules import (
    RuleContext,
    extract_gstin,
    extract_invoice_number,
    extract_pan,
    normalize_gstin,
    normalize_pan,
)
from app.services.extraction.service import ExtractionService

__all__ = [
    "ExtractionService",
    "RuleContext",
    "extract_gstin",
    "extract_invoice_number",
    "extract_pan",
    "normalize_gstin",
    "normalize_pan",
]
