"""
PaddleOCR implementation (optional).

Requires: pip install paddlepaddle paddleocr
This is gated behind a try/except import so the app starts fine without it.

PaddleOCR PP-OCRv4 offers better accuracy on dense/rotated text and
built-in angle classification, making it the superior choice for
production invoice processing when GPU resources are available.
"""

import asyncio
from functools import partial

import numpy as np

from app.adapters.ocr.base import OCREngine, OCRResult, OCRWord
from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    from paddleocr import PaddleOCR as _PaddleOCR

    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False
    logger.info(
        "paddleocr_not_installed",
        message="PaddleOCR not available, install with: pip install paddlepaddle paddleocr",
    )


class PaddleOCREngine(OCREngine):
    """
    PaddleOCR PP-OCRv4 adapter.

    Advantages: Fast, strong on dense/rotated text, built-in angle classifier.
    Use as: Primary engine when accuracy matters and GPU is available.
    """

    def __init__(self, use_angle_cls: bool = True, lang: str = "en"):
        if not PADDLE_AVAILABLE:
            raise ImportError(
                "PaddleOCR is not installed. Install with: pip install paddlepaddle paddleocr"
            )
        self._ocr = _PaddleOCR(
            use_angle_cls=use_angle_cls,
            lang=lang,
            show_log=False,
        )
        logger.info("paddleocr_initialized", lang=lang, angle_cls=use_angle_cls)

    @property
    def name(self) -> str:
        return "paddleocr"

    async def extract(self, image: np.ndarray) -> OCRResult:
        """Run PaddleOCR in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._extract_sync, image))

    def _extract_sync(self, image: np.ndarray) -> OCRResult:
        """Synchronous PaddleOCR extraction."""
        result = self._ocr.ocr(image, cls=True)

        words: list[OCRWord] = []
        raw_lines: list[str] = []
        confidences: list[float] = []

        if result and result[0]:
            for line in result[0]:
                bbox_points = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text, confidence = line[1]

                if not text.strip():
                    continue

                # Convert quadrilateral to axis-aligned bounding box
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                x0, y0 = int(min(xs)), int(min(ys))
                x1, y1 = int(max(xs)), int(max(ys))

                confidences.append(confidence)
                raw_lines.append(text)

                # PaddleOCR returns lines, not words — split into words
                line_words = text.split()
                word_width = (x1 - x0) // max(len(line_words), 1)
                for j, word in enumerate(line_words):
                    words.append(
                        OCRWord(
                            text=word,
                            confidence=confidence,
                            x=x0 + j * word_width,
                            y=y0,
                            width=word_width,
                            height=y1 - y0,
                            page=0,
                        )
                    )

        raw_text = "\n".join(raw_lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        logger.info(
            "paddleocr_complete",
            word_count=len(words),
            avg_confidence=round(avg_conf, 3),
        )

        return OCRResult(
            raw_text=raw_text,
            words=words,
            average_confidence=avg_conf,
            engine_name=self.name,
        )

    async def health_check(self) -> bool:
        """Verify PaddleOCR is loaded."""
        return PADDLE_AVAILABLE and self._ocr is not None
