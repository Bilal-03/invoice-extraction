"""Deterministic, layout-aware invoice extraction rules.

The extraction package is deliberately provider-independent.  It consumes the
stable :class:`~app.adapters.ocr.base.OCRResult` contract, so PaddleOCR,
Tesseract, a PDF text layer, and a future local VLM can all feed the same
rules.  The richer field values retain confidence, source, and page evidence.
"""

from app.extraction.context import RuleContext
from app.extraction.gst import extract_gstin, is_valid_gstin_syntax, normalize_gstin
from app.extraction.invoice_number import extract_invoice_number
from app.extraction.pan import extract_pan, is_valid_pan, normalize_pan

__all__ = [
    "RuleContext",
    "extract_gstin",
    "extract_invoice_number",
    "extract_pan",
    "is_valid_gstin_syntax",
    "is_valid_pan",
    "normalize_gstin",
    "normalize_pan",
]
