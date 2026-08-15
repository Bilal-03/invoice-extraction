"""Buyer/customer rule family."""

from __future__ import annotations

from typing import Any

from app.adapters.ocr.base import OCRResult
from app.domain.schemas import BuyerDetails
from app.extraction.context import RuleContext
from app.extraction.pan import extract_party_pans


def extract_buyer(result: OCRResult, legacy_extractor: Any) -> BuyerDetails | None:
    """Use the existing spatial party-block rules across every OCR page."""

    buyer = legacy_extractor._extract_buyer(result.raw_text, RuleContext(result).all_lines())
    _, buyer_pan = extract_party_pans(result)
    if buyer is None:
        return BuyerDetails(pan=buyer_pan) if buyer_pan is not None else None
    return buyer.model_copy(update={"pan": buyer_pan}) if buyer_pan is not None else buyer
