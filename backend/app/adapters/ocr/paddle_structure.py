"""Optional PaddleOCR 3.x / PP-StructureV3 adapter.

PP-StructureV3 is the preferred local-full engine. PaddleOCR result objects
changed shape between releases, so this adapter normalises the documented
``predict`` output and older ``ocr`` output into the stable word/bounding-box
contract used by the extraction and review layers.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from functools import partial
from typing import Any

import numpy as np

from app.adapters.ocr.base import OCREngine, OCRResult, OCRWord
from app.core.logging import get_logger

logger = get_logger(__name__)

try:  # PaddlePaddle can fail at import time when the optional wheel is incompatible.
    from paddleocr import PPStructureV3 as _PPStructureV3
except Exception:  # pragma: no cover - depends on the optional local install
    _PPStructureV3 = None

try:
    from paddleocr import PaddleOCR as _PaddleOCR
except Exception:  # pragma: no cover - depends on the optional local install
    _PaddleOCR = None

PADDLE_STRUCTURE_AVAILABLE = _PPStructureV3 is not None
PADDLE_AVAILABLE = _PaddleOCR is not None


def _call_or_value(value: Any) -> Any:
    if callable(value):
        try:
            return value()
        except TypeError:
            return value
    return value


def _unwrap(value: Any) -> Any:
    """Turn Paddle result wrappers into mappings/lists without one-version coupling."""
    if isinstance(value, (Mapping, list, tuple, str)):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
    for attribute in ("json", "data", "res"):
        candidate = getattr(value, attribute, None)
        if candidate is None:
            continue
        candidate = _call_or_value(candidate)
        if candidate is not value:
            return _unwrap(candidate)
    return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _text_list(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        if isinstance(item, (list, tuple)):
            result.extend(_text_list(item))
        elif item is not None and str(item).strip():
            result.append(str(item).strip())
    return result


def _score_list(value: Any) -> list[float]:
    scores: list[float] = []
    for item in _as_list(value):
        try:
            scores.append(float(item))
        except (TypeError, ValueError):
            scores.append(0.0)
    return scores


def _box(value: Any) -> tuple[int, int, int, int] | None:
    """Convert rectangles, quadrilaterals, and Paddle dict boxes to x/y bounds."""
    if isinstance(value, Mapping):
        candidates = (
            (value.get("x0"), value.get("y0"), value.get("x1"), value.get("y1")),
            (value.get("xmin"), value.get("ymin"), value.get("xmax"), value.get("ymax")),
        )
        for candidate in candidates:
            if all(item is not None for item in candidate):
                return tuple(round(float(item)) for item in candidate)  # type: ignore[return-value]
        return None

    if isinstance(value, np.ndarray):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        return None
    if len(value) == 4 and all(isinstance(item, (int, float)) for item in value):
        x0, y0, x1, y1 = value
        return round(float(x0)), round(float(y0)), round(float(x1)), round(float(y1))

    points: list[tuple[float, float]] = []
    for point in value:
        if isinstance(point, np.ndarray):
            point = point.tolist()
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not points:
        return None
    xs, ys = zip(*points, strict=True)
    return round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))


def _normalise_score(value: float) -> float:
    return value / 100 if value > 1 else max(0.0, value)


class _ResultCollector:
    def __init__(self, page: int, engine_name: str):
        self.page = page
        self.engine_name = engine_name
        self.words: list[OCRWord] = []
        self.lines: list[str] = []
        self.scores: list[float] = []
        self.regions: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self._has_ocr_lines = False
        self._seen: set[int] = set()

    def add_region(self, text: Any, box: Any = None, label: str | None = None) -> None:
        rect = _box(box)
        if rect and text is not None and str(text).strip():
            x0, y0, x1, y1 = rect
            self.regions.append(
                {"text": str(text).strip(), "bbox": [x0, y0, x1, y1], "label": label or "text"}
            )

    def add_line(
        self,
        text: Any,
        box: Any = None,
        score: Any = None,
        label: str | None = None,
    ) -> None:
        if text is None or not str(text).strip():
            return
        line = str(text).strip()
        rect = _box(box)
        confidence = _normalise_score(float(score)) if score is not None else 0.0
        self.lines.append(line)
        self.scores.append(confidence)
        self.add_region(line, rect, label)
        parts = line.split()
        if not parts:
            return
        x0, y0, x1, y1 = rect or (0, 0, max(len(line), 1), 1)
        width = max(1, x1 - x0)
        part_width = max(1, width // len(parts))
        for index, part in enumerate(parts):
            word_x = x0 + index * part_width
            word_width = part_width if index < len(parts) - 1 else max(1, x1 - word_x)
            self.words.append(
                OCRWord(
                    text=part,
                    confidence=confidence,
                    x=word_x,
                    y=y0,
                    width=word_width,
                    height=max(1, y1 - y0),
                    page=self.page,
                )
            )

    def collect(self, value: Any) -> None:
        value = _unwrap(value)
        if isinstance(value, (Mapping, list, tuple)):
            identity = id(value)
            if identity in self._seen:
                return
            self._seen.add(identity)

        if isinstance(value, Mapping):
            text_key = next(
                (key for key in ("rec_texts", "texts", "text_lines") if key in value), None
            )
            box_key = next(
                (
                    key
                    for key in ("rec_boxes", "dt_polys", "rec_polys", "text_region")
                    if key in value
                ),
                None,
            )
            score_key = next(
                (key for key in ("rec_scores", "scores", "text_scores") if key in value), None
            )
            if text_key:
                self._has_ocr_lines = True
                texts = _text_list(value.get(text_key))
                boxes = _as_list(value.get(box_key)) if box_key else []
                scores = _score_list(value.get(score_key)) if score_key else []
                for index, text in enumerate(texts):
                    self.add_line(
                        text,
                        boxes[index] if index < len(boxes) else None,
                        scores[index] if index < len(scores) else None,
                    )

            if "block_content" in value:
                block_label = str(value.get("block_label") or "layout")
                block_content = value.get("block_content")
                block_box = value.get("block_bbox") or value.get("bbox")
                if self._has_ocr_lines:
                    self.add_region(block_content, block_box, block_label)
                else:
                    self.add_line(block_content, block_box, value.get("score"), block_label)

            if "table_res_list" in value:
                for table in _as_list(value.get("table_res_list")):
                    table = _unwrap(table)
                    if not isinstance(table, Mapping):
                        continue
                    ocr_table = table.get("table_ocr_pred") or {}
                    if not isinstance(ocr_table, Mapping):
                        ocr_table = {}
                    self.tables.append(
                        {
                            "html": str(table.get("pred_html") or "")[:40_000],
                            "cells": _text_list(ocr_table.get("rec_texts"))[:500],
                        }
                    )

            for key in (
                "overall_ocr_res",
                "ocr_res",
                "ocr_result",
                "parsing_res_list",
                "table_res_list",
                "layout_res_list",
                "res",
                "result",
            ):
                if key in value:
                    self.collect(value[key])
            return

        if isinstance(value, (list, tuple)):
            # PaddleOCR <=2.x shape: [ [quad, (text, confidence)], ... ].
            if len(value) == 2 and isinstance(value[1], (list, tuple)):
                text_value = value[1][0] if value[1] else None
                score_value = value[1][1] if len(value[1]) > 1 else None
                self.add_line(text_value, value[0], score_value)
                return
            for item in value:
                self.collect(item)

    def result(self, image: np.ndarray) -> OCRResult:
        confidences = [word.confidence for word in self.words if word.confidence > 0]
        if not confidences:
            confidences = [score for score in self.scores if score > 0]
        structured_data = {"engine": self.engine_name, "regions": self.regions[:500]}
        if self.tables:
            structured_data["tables"] = self.tables[:50]
        return OCRResult(
            raw_text="\n".join(dict.fromkeys(self.lines)),
            words=self.words,
            average_confidence=sum(confidences) / len(confidences) if confidences else 0.0,
            engine_name=self.engine_name,
            page_count=1,
            page_dimensions={self.page: (int(image.shape[1]), int(image.shape[0]))},
            structured_data=structured_data,
        )


def _normalise_result(result: Any, image: np.ndarray, engine_name: str) -> OCRResult:
    collector = _ResultCollector(page=0, engine_name=engine_name)
    collector.collect(result)
    return collector.result(image)


class PaddleStructureV3OCREngine(OCREngine):
    """Use PP-StructureV3 first, then PaddleOCR, then let the caller use Tesseract."""

    def __init__(self, device: str = "cpu", lang: str = "en"):
        if _PPStructureV3 is not None:
            self._engine_name = "pp-structure-v3"
            try:
                self._pipeline = _PPStructureV3(device=device)
            except TypeError:  # Older PP-StructureV3 builds expose fewer kwargs.
                self._pipeline = _PPStructureV3()
            self._ocr = None
        elif _PaddleOCR is not None:
            self._engine_name = "paddleocr"
            try:
                self._ocr = _PaddleOCR(
                    lang=lang,
                    device=device,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                )
            except TypeError:
                self._ocr = _PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
            self._pipeline = None
        else:
            raise ImportError("PaddleOCR is not installed. Install the optional local-full extra.")
        logger.info("paddle_engine_initialized", engine=self._engine_name, device=device)

    @property
    def name(self) -> str:
        return self._engine_name

    async def extract(self, image: np.ndarray) -> OCRResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._extract_sync, image))

    def _extract_sync(self, image: np.ndarray) -> OCRResult:
        if self._pipeline is not None:
            try:
                prediction = self._pipeline.predict(input=image)
            except TypeError:
                prediction = self._pipeline.predict(image)
        elif hasattr(self._ocr, "predict"):
            prediction = self._ocr.predict(image)
        else:  # PaddleOCR <=2.x compatibility.
            prediction = self._ocr.ocr(image, cls=True)
        if not isinstance(prediction, (Mapping, list, tuple, str)) and hasattr(
            prediction, "__iter__"
        ):
            prediction = list(prediction)
        return _normalise_result(prediction, image, self._engine_name)

    async def health_check(self) -> bool:
        return self._pipeline is not None or self._ocr is not None


# Exposed for adapter tests without requiring PaddlePaddle itself.
normalise_paddle_result = _normalise_result
