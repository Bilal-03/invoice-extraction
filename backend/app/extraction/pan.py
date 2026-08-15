"""Deterministic PAN extraction and local syntax validation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.adapters.ocr.base import OCRResult, OCRWord
from app.domain.schemas import FieldValue
from app.extraction.context import RuleContext

PAN_PATTERN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]", re.IGNORECASE)
PAN_CANDIDATE_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z]{5}[0-9]{4}[A-Z])(?![A-Z0-9])", re.IGNORECASE
)
PAN_LABELS = (
    "permanent account number",
    "pan number",
    "pan no",
    "pan",
)
SELLER_PAN_LABELS = (
    "seller pan",
    "supplier pan",
    "vendor pan",
    "sold by pan",
    "seller's pan",
)
BUYER_PAN_LABELS = (
    "buyer pan",
    "customer pan",
    "bill to pan",
    "billed to pan",
    "recipient pan",
    "ship to pan",
)

SELLER_ANCHOR_WORDS = {"seller", "supplier", "vendor", "sold", "from"}
BUYER_ANCHOR_WORDS = {
    "buyer",
    "customer",
    "recipient",
    "bill",
    "billed",
    "ship",
    "shipping",
}


@dataclass(frozen=True)
class _PanCandidate:
    field: FieldValue
    line_index: int | None
    page: int | None
    x_center: float | None
    y_center: float | None
    prefix: str = ""


def normalize_pan(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def is_valid_pan(value: str | None) -> bool:
    return bool(value and PAN_PATTERN.fullmatch(value.strip().upper()))


def extract_party_pans(result: OCRResult) -> tuple[FieldValue | None, FieldValue | None]:
    """Return ``(seller_pan, buyer_pan)`` using labels and page geometry.

    PAN is frequently printed as just ``PAN:`` in both party blocks.  The
    classifier therefore scores nearby seller/buyer anchor words first and
    uses the left/right position of the PAN value as a deterministic fallback.
    Explicit labels such as ``Buyer PAN`` always take precedence.
    """

    context = RuleContext(result)
    candidates = _find_candidates(context)
    seller_explicit = _explicit_candidate(context, SELLER_PAN_LABELS)
    buyer_explicit = _explicit_candidate(context, BUYER_PAN_LABELS)

    seller = seller_explicit
    buyer = buyer_explicit
    for candidate in candidates:
        if _same_value(candidate.field, seller) or _same_value(candidate.field, buyer):
            continue
        party = _classify_candidate(candidate, context.all_lines(), result)
        if party == "buyer" and buyer is None:
            buyer = candidate.field
        elif seller is None:
            seller = candidate.field
        elif buyer is None:
            buyer = candidate.field
    return seller, buyer


def extract_pan(result: OCRResult) -> FieldValue | None:
    """Backward-compatible single-PAN API; returns the seller/first PAN."""

    seller, buyer = extract_party_pans(result)
    return seller or buyer


def _explicit_candidate(context: RuleContext, labels: tuple[str, ...]) -> FieldValue | None:
    match = context.find_labeled_value(labels, PAN_CANDIDATE_PATTERN)
    if match is None:
        return None
    return _field_from_match(context, match.value, match.confidence, match.page, match.words)


def _find_candidates(context: RuleContext) -> list[_PanCandidate]:
    candidates: list[_PanCandidate] = []
    lines = context.all_lines()
    for line_index, line in enumerate(lines):
        if not line:
            continue
        line_text = " ".join(word.text for word in line)
        for match in PAN_CANDIDATE_PATTERN.finditer(line_text):
            value = normalize_pan(match.group(1))
            if len(value) != 10:
                continue
            words = context._words_for_value(line, value)
            field = _field_from_match(
                context,
                value,
                0.95 if is_valid_pan(value) else 0.72,
                line[0].page,
                words,
            )
            selected = words or tuple(line)
            candidates.append(
                _PanCandidate(
                    field=field,
                    line_index=line_index,
                    page=line[0].page,
                    x_center=(
                        sum(word.x + word.width / 2 for word in selected) / len(selected)
                        if selected
                        else None
                    ),
                    y_center=(
                        sum(word.y + word.height / 2 for word in selected) / len(selected)
                        if selected
                        else None
                    ),
                    prefix=line_text[: match.start()],
                )
            )
    if candidates:
        return candidates
    fallback = context.find_text(PAN_CANDIDATE_PATTERN)
    if fallback is None:
        return []
    return [
        _PanCandidate(
            field=_field_from_match(context, fallback.value, fallback.confidence, None, ()),
            line_index=None,
            page=None,
            x_center=None,
            y_center=None,
        )
    ]


def _classify_candidate(
    candidate: _PanCandidate,
    lines: list[list[OCRWord]],
    result: OCRResult,
) -> str:
    prefix = candidate.prefix.casefold()
    if any(word in prefix for word in SELLER_ANCHOR_WORDS):
        return "seller"
    if any(word in prefix for word in BUYER_ANCHOR_WORDS):
        return "buyer"

    seller_score = _nearest_anchor_score(candidate, lines, SELLER_ANCHOR_WORDS)
    buyer_score = _nearest_anchor_score(candidate, lines, BUYER_ANCHOR_WORDS)
    if seller_score is not None or buyer_score is not None:
        if buyer_score is None:
            return "seller"
        if seller_score is None:
            return "buyer"
        return "seller" if seller_score <= buyer_score else "buyer"

    if candidate.page is not None and candidate.x_center is not None:
        width = result.page_dimensions.get(candidate.page, (0, 0))[0]
        if width:
            return "seller" if candidate.x_center < width / 2 else "buyer"
    return "seller"


def _nearest_anchor_score(
    candidate: _PanCandidate,
    lines: list[list[OCRWord]],
    anchor_words: set[str],
) -> float | None:
    if candidate.line_index is None or candidate.x_center is None or candidate.y_center is None:
        return None
    best: float | None = None
    start = max(0, candidate.line_index - 12)
    end = min(len(lines), candidate.line_index + 3)
    for line in lines[start:end]:
        for word in line:
            if word.text.casefold().strip("*:;,.-") not in anchor_words:
                continue
            if candidate.page != word.page:
                continue
            vertical = abs(candidate.y_center - (word.y + word.height / 2))
            horizontal = abs(candidate.x_center - (word.x + word.width / 2))
            score = vertical + horizontal * 0.15
            best = score if best is None else min(best, score)
    return best


def _field_from_match(
    context: RuleContext,
    value: str,
    confidence: float,
    page: int | None,
    words: tuple[OCRWord, ...],
) -> FieldValue:
    return context.field_value(
        normalize_pan(value),
        min(0.99, max(confidence, 0.72)),
        page=page,
        words=words,
    )


def _same_value(left: FieldValue, right: FieldValue | None) -> bool:
    return right is not None and left.value is not None and left.value == right.value
