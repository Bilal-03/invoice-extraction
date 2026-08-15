"""Payment-terms rule family."""

from app.adapters.ocr.base import OCRResult
from app.extraction.context import RuleContext


def extract_payment_terms(result: OCRResult) -> str | None:
    return RuleContext(result).labeled_text(("payment terms", "payment term", "terms"))
