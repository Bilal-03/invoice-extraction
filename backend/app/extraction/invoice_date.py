"""Deterministic invoice and due-date extraction rules."""

from __future__ import annotations

import re

from app.adapters.ocr.base import OCRResult
from app.extraction.context import RuleContext

DATE_PATTERN = re.compile(
    r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}[/\-.]\d{1,2}[/\-.]\d{1,2}|"
    r"\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+\w+\s+\d{4})",
    re.IGNORECASE,
)

INVOICE_DATE_LABELS = (
    "invoice date",
    "date of invoice",
    "inv date",
    "billing date",
    "invoice dt",
    "dated",
    "date",
)

DUE_DATE_LABELS = (
    "due date",
    "payment due",
    "due by",
    "pay by",
    "due on",
    "payment date",
    "due dt",
)


def extract_dates(result: OCRResult) -> dict[str, str | None]:
    context = RuleContext(result)
    due = _extract_labeled(context, DUE_DATE_LABELS)
    invoice = _extract_labeled(context, INVOICE_DATE_LABELS, exclude_if_contains=("due", "payment"))
    if invoice is None:
        fallback = context.find_text(DATE_PATTERN)
        invoice = fallback.value if fallback else None
    return {"invoice_date": invoice, "due_date": due}


def _extract_labeled(
    context: RuleContext,
    labels: tuple[str, ...],
    *,
    exclude_if_contains: tuple[str, ...] = (),
) -> str | None:
    match = context.find_labeled_value(
        labels,
        DATE_PATTERN,
        max_following_lines=1,
        exclude_if_contains=exclude_if_contains,
    )
    return match.value if match else None
