"""
VLM (Vision-Language Model) client interface.

This is the confidence-gated fallback layer — NOT the primary extraction
path. The architecture story is: "I used a VLM only where deterministic
models were uncertain, to control cost and latency."

VLM is triggered when:
  - Overall OCR confidence < threshold (configurable)
  - Required fields are missing after regex extraction
"""

from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from app.domain.schemas import InvoiceExtraction, InvoiceQuestionResponse


class VLMClient(ABC):
    """
    Abstract VLM client for invoice field extraction fallback.

    Implementations should use structured output / function-calling mode
    so the VLM returns JSON conforming to InvoiceExtraction directly.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Model name for logging and cost tracking."""
        ...

    @abstractmethod
    async def extract_fields(
        self,
        image: np.ndarray,
        existing_extraction: InvoiceExtraction | None = None,
    ) -> InvoiceExtraction:
        """
        Extract invoice fields from an image using a VLM.

        Args:
            image: The original document image (not preprocessed).
            existing_extraction: Partial extraction from OCR/regex
                                 to provide as context (helps the VLM
                                 fill in gaps rather than re-extract everything).

        Returns:
            Complete or supplemental InvoiceExtraction result.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the VLM API is reachable."""
        ...

    async def answer_question(
        self,
        question: str,
        invoice_json: dict[str, Any],
        ocr_text: str,
    ) -> InvoiceQuestionResponse:
        """Answer a grounded invoice question when the provider supports it."""

        raise NotImplementedError(f"{self.name} does not support invoice Q&A")
