"""Supplier/vendor rule family."""

from __future__ import annotations

from typing import Any

from app.adapters.ocr.base import OCRResult
from app.domain.schemas import VendorDetails
from app.extraction.context import RuleContext
from app.extraction.gst import extract_gstin
from app.extraction.pan import extract_party_pans


def extract_supplier(result: OCRResult, legacy_extractor: Any) -> VendorDetails:
    """Keep the mature party-section heuristics and add explicit ID rules."""

    vendor = legacy_extractor._extract_vendor(
        result.raw_text,
        result.words,
        RuleContext(result).all_lines(),
    )
    gstin = extract_gstin(result)
    pan, _ = extract_party_pans(result)
    updates = {}
    if gstin is not None:
        updates["gstin"] = gstin
    if pan is not None:
        updates["pan"] = pan
    return vendor.model_copy(update=updates) if updates else vendor
