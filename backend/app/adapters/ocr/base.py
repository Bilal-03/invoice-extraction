"""
OCR Engine interface — the key architectural abstraction.

This is the Dependency Inversion Principle in action:
  - ExtractionService depends on OCREngine (the interface)
  - NOT on TesseractOCR or PaddleOCR directly
  - Engines are swapped via configuration, injected via FastAPI Depends()
  - Tests mock this interface without touching any real OCR engine

This pattern is the #1 thing that separates "notebook code wrapped in Flask"
from "engineered backend service."
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class OCRWord:
    """A single word detected by OCR, with spatial and confidence metadata."""

    text: str
    confidence: float  # 0.0 to 1.0
    x: int  # Left position (pixels)
    y: int  # Top position (pixels)
    width: int
    height: int
    page: int = 0  # For multi-page documents

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        """Return (x0, y0, x1, y1) bounding box."""
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass
class OCRResult:
    """
    Complete OCR output for a single page or document.

    Contains both the raw text and word-level detail — the word-level
    data is what enables spatial-aware extraction (knowing where on the
    page a value sits) and the bounding-box overlay in the dashboard.
    """

    raw_text: str
    words: list[OCRWord] = field(default_factory=list)
    average_confidence: float = 0.0
    engine_name: str = "unknown"
    page_count: int = 1
    page_dimensions: dict[int, tuple[int, int]] = field(default_factory=dict)

    def text_in_region(self, x0: int, y0: int, x1: int, y1: int, page: int = 0) -> list[OCRWord]:
        """Return all words whose bounding box overlaps the given region."""
        result = []
        for word in self.words:
            if word.page != page:
                continue
            wx0, wy0, wx1, wy1 = word.bbox
            # Check for overlap
            if wx0 < x1 and wx1 > x0 and wy0 < y1 and wy1 > y0:
                result.append(word)
        return result

    def lines(self, page: int = 0, line_threshold: int = 10) -> list[list[OCRWord]]:
        """
        Group words into lines based on Y-coordinate proximity.
        Words within `line_threshold` pixels of each other vertically
        are considered on the same line.
        """
        page_words = sorted(
            [w for w in self.words if w.page == page],
            key=lambda w: (w.y, w.x),
        )
        if not page_words:
            return []

        lines: list[list[OCRWord]] = [[page_words[0]]]
        for word in page_words[1:]:
            if abs(word.y - lines[-1][0].y) <= line_threshold:
                lines[-1].append(word)
            else:
                lines.append([word])

        # Sort words within each line by x position
        for line in lines:
            line.sort(key=lambda w: w.x)

        return lines


class OCREngine(ABC):
    """
    Abstract base class for OCR engines.

    Implementations:
      - TesseractOCR: System Tesseract via pytesseract (default)
      - PaddleOCREngine: PaddleOCR PP-OCRv4 (optional, higher accuracy)

    The interface guarantees word-level bounding boxes and confidence
    scores, not just raw text — this is critical for spatial extraction.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name for logging and analytics."""
        ...

    @abstractmethod
    async def extract(self, image: np.ndarray) -> OCRResult:
        """
        Run OCR on a preprocessed image.

        Args:
            image: OpenCV image array (BGR or grayscale).

        Returns:
            OCRResult with raw text, word-level bounding boxes, and confidence.
        """
        ...

    async def health_check(self) -> bool:
        """Verify the engine is available and functional."""
        return True
