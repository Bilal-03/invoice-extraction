"""
Tesseract OCR implementation.

Uses pytesseract.image_to_data() (not image_to_string()) to get
word-level bounding boxes and per-word confidence scores — this is
the critical difference from the original app.py that only used
image_to_string() and lost all spatial information.
"""

import asyncio
from functools import partial

import numpy as np
import pytesseract

from app.adapters.ocr.base import OCREngine, OCRResult, OCRWord
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class TesseractOCR(OCREngine):
    """
    Tesseract OCR engine adapter.

    Advantages: zero GPU dependency, fastest to deploy, pre-installed on most systems.
    Use as: default engine / CPU-only environments / fallback.
    """

    def __init__(self, tesseract_cmd: str | None = None):
        settings = get_settings()
        if tesseract_cmd or settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd or settings.tesseract_cmd

    @property
    def name(self) -> str:
        return "tesseract"

    async def extract(self, image: np.ndarray) -> OCRResult:
        """
        Run Tesseract OCR with word-level detail.

        Runs in a thread pool to avoid blocking the async event loop,
        since pytesseract is a blocking subprocess call.
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, partial(self._extract_sync, image))
        return result

    def _extract_sync(self, image: np.ndarray) -> OCRResult:
        """Synchronous extraction — called in thread pool."""
        # Get word-level data with bounding boxes and confidence
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",  # Assume uniform block of text
        )

        words: list[OCRWord] = []
        confidences: list[float] = []

        n_items = len(data["text"])
        for i in range(n_items):
            text = str(data["text"][i]).strip()
            conf = int(data["conf"][i])

            # Skip empty text and low-confidence noise (Tesseract returns -1 for non-text)
            if not text or conf < 0:
                continue

            confidence = conf / 100.0
            confidences.append(confidence)

            words.append(
                OCRWord(
                    text=text,
                    confidence=confidence,
                    x=int(data["left"][i]),
                    y=int(data["top"][i]),
                    width=int(data["width"][i]),
                    height=int(data["height"][i]),
                    page=0,
                )
            )

        # image_to_data already invokes Tesseract. Avoid a second full OCR pass.
        raw_text = " ".join(word.text for word in words)

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        logger.info(
            "tesseract_ocr_complete",
            word_count=len(words),
            avg_confidence=round(avg_confidence, 3),
            text_length=len(raw_text),
        )

        return OCRResult(
            raw_text=raw_text,
            words=words,
            average_confidence=avg_confidence,
            engine_name=self.name,
        )

    async def health_check(self) -> bool:
        """Verify Tesseract is installed and reachable."""
        try:
            version = pytesseract.get_tesseract_version()
            logger.info("tesseract_health_ok", version=str(version))
            return True
        except Exception as e:
            logger.error("tesseract_health_fail", error=str(e))
            return False
