"""Shared spatial helpers for deterministic invoice rules."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.adapters.ocr.base import OCRResult, OCRWord
from app.domain.schemas import BoundingBox, ExtractionSource, FieldValue


def compact(value: str) -> str:
    """Normalise OCR text for comparisons while retaining human text elsewhere."""

    return re.sub(r"\s+", " ", value or "").strip()


def token_key(value: str) -> str:
    """Return a case-insensitive alphanumeric OCR comparison key."""

    return re.sub(r"[^a-z0-9]", "", value.casefold())


@dataclass(frozen=True)
class RuleMatch:
    """A rule match with its page and OCR confidence evidence."""

    value: str
    confidence: float
    page: int | None = None
    words: tuple[OCRWord, ...] = ()


class RuleContext:
    """Layout-aware view over an OCR result used by all deterministic rules.

    A rule first searches the OCR line containing its label and then a small
    number of following lines on the same page.  This keeps values attached to
    their visual labels instead of selecting an unrelated value elsewhere in a
    document.  The context also converts the matched OCR words into the
    normalised bounding boxes used by the review UI.
    """

    def __init__(self, result: OCRResult):
        self.result = result

    @property
    def text(self) -> str:
        return self.result.raw_text or ""

    def all_lines(self) -> list[list[OCRWord]]:
        """Return visual lines for every page in reading order."""

        return self.result.all_lines()

    def field_value(
        self,
        value: str | None,
        confidence: float,
        *,
        source: ExtractionSource = ExtractionSource.OCR_RULE,
        page: int | None = None,
        words: tuple[OCRWord, ...] = (),
    ) -> FieldValue:
        """Build a provenance-rich field value with the best evidence box."""

        bbox = self.bounding_box(value, page=page, words=words) if value else None
        return FieldValue(
            value=value,
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            bounding_box=bbox,
        )

    def bounding_box(
        self,
        value: str | None,
        *,
        page: int | None = None,
        words: tuple[OCRWord, ...] = (),
    ) -> BoundingBox | None:
        """Find a value across one or more adjacent OCR tokens.

        OCR engines may return ``INV-2026-3321`` as one token or as three
        tokens.  Comparing the concatenated normalised token stream handles
        both forms and still produces one union bounding box.
        """

        target = token_key(value or "")
        if not target:
            return None

        candidates = list(words) if words else list(self.result.words)
        if page is not None:
            candidates = [word for word in candidates if word.page == page]
        candidates.sort(key=lambda word: (word.page, word.y, word.x))

        for start, first in enumerate(candidates):
            if not token_key(first.text):
                continue
            joined = ""
            selected: list[OCRWord] = []
            for candidate in candidates[start : start + 12]:
                if selected and candidate.page != selected[-1].page:
                    break
                part = token_key(candidate.text)
                if not part:
                    continue
                joined += part
                selected.append(candidate)
                if joined == target:
                    return self._union_box(selected)
                if len(joined) >= len(target):
                    break
        return None

    def find_labeled_value(
        self,
        labels: tuple[str, ...],
        value_pattern: str | re.Pattern[str],
        *,
        max_following_lines: int = 2,
        exclude_if_contains: tuple[str, ...] = (),
    ) -> RuleMatch | None:
        """Find a regex value on the same or nearby line as a label."""

        pattern = (
            re.compile(value_pattern, re.IGNORECASE)
            if isinstance(value_pattern, str)
            else value_pattern
        )
        label_pattern = re.compile(
            r"(?:"
            + "|".join(re.escape(compact(label)) for label in sorted(labels, key=len, reverse=True))
            + r")",
            re.IGNORECASE,
        )

        lines = self.all_lines()
        for index, line in enumerate(lines):
            if not line:
                continue
            line_text = compact(" ".join(word.text for word in line))
            label_match = label_pattern.search(line_text)
            if not label_match:
                continue
            prefix = line_text[: label_match.start()].casefold()
            if any(excluded.casefold() in prefix for excluded in exclude_if_contains):
                continue

            for offset in range(max_following_lines + 1):
                candidate_index = index + offset
                if candidate_index >= len(lines):
                    break
                candidate_line = lines[candidate_index]
                if not candidate_line or candidate_line[0].page != line[0].page:
                    break
                candidate_text = compact(" ".join(word.text for word in candidate_line))
                search_text = (
                    candidate_text[label_match.end() :]
                    if offset == 0 and candidate_index == index
                    else candidate_text
                )
                match = pattern.search(search_text)
                if not match:
                    continue
                value = compact(match.group(1) if match.lastindex else match.group(0))
                if not value:
                    continue
                matched_words = self._words_for_value(candidate_line, value)
                confidence = self._confidence(matched_words or tuple(candidate_line))
                return RuleMatch(
                    value=value,
                    confidence=confidence,
                    page=candidate_line[0].page,
                    words=matched_words,
                )
        # Native PDF text layers can provide raw text without word boxes.  It
        # still deserves label-aware deterministic extraction; the field will
        # simply have no coordinate evidence until an OCR/layout pass runs.
        raw_pattern = re.compile(
            r"(?:"
            + "|".join(re.escape(compact(label)) for label in sorted(labels, key=len, reverse=True))
            + r")\s*[:#-]?\s*"
            + pattern.pattern,
            re.IGNORECASE,
        )
        for raw_match in raw_pattern.finditer(self.text):
            prefix = self.text[: raw_match.start()].casefold()
            if any(excluded.casefold() in prefix[-80:] for excluded in exclude_if_contains):
                continue
            value = compact(raw_match.group(1) if raw_match.lastindex else raw_match.group(0))
            if value:
                return RuleMatch(value=value, confidence=0.78)
        return None

    def find_text(self, pattern: str | re.Pattern[str]) -> RuleMatch | None:
        """Find the first capture in the raw OCR text as a fallback."""

        compiled = re.compile(pattern, re.IGNORECASE) if isinstance(pattern, str) else pattern
        match = compiled.search(self.text)
        if not match:
            return None
        value = compact(match.group(1) if match.lastindex else match.group(0))
        return RuleMatch(value=value, confidence=0.78)

    def labeled_text(
        self,
        labels: tuple[str, ...],
        *,
        max_length: int = 80,
    ) -> str | None:
        """Extract a short human-readable value following a textual label."""

        lines = self.all_lines()
        pattern = re.compile(
            r"(?:"
            + "|".join(re.escape(compact(label)) for label in sorted(labels, key=len, reverse=True))
            + r")"
            r"\s*[:#-]?\s*(.+)$",
            re.IGNORECASE,
        )
        for line in lines:
            line_text = compact(" ".join(word.text for word in line))
            match = pattern.search(line_text)
            if match:
                value = compact(match.group(1))
                if value:
                    return value[:max_length]
        fallback = re.search(pattern, self.text)
        return compact(fallback.group(1))[:max_length] if fallback else None

    def _words_for_value(self, line: list[OCRWord], value: str) -> tuple[OCRWord, ...]:
        target = token_key(value)
        if not target:
            return ()
        for start in range(len(line)):
            joined = ""
            selected: list[OCRWord] = []
            for candidate in line[start:]:
                part = token_key(candidate.text)
                if not part:
                    continue
                joined += part
                selected.append(candidate)
                if joined == target:
                    return tuple(selected)
                if len(joined) >= len(target):
                    break
        return ()

    @staticmethod
    def _confidence(words: tuple[OCRWord, ...]) -> float:
        scores = [word.confidence for word in words if word.confidence > 0]
        return sum(scores) / len(scores) if scores else 0.78

    def _union_box(self, words: list[OCRWord]) -> BoundingBox | None:
        if not words:
            return None
        page = words[0].page
        width, height = self.result.page_dimensions.get(page, (0, 0))
        if not width or not height:
            return None
        return BoundingBox(
            x0=max(0.0, min(word.x for word in words) / width),
            y0=max(0.0, min(word.y for word in words) / height),
            x1=min(1.0, max(word.x + word.width for word in words) / width),
            y1=min(1.0, max(word.y + word.height for word in words) / height),
            page=page,
        )
