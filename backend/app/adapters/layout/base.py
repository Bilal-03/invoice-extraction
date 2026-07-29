"""Interface for swappable layout-aware field extraction strategies."""

from abc import ABC, abstractmethod

from app.adapters.ocr.base import OCRResult
from app.domain.schemas import InvoiceExtraction


class LayoutExtractor(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def extract(self, ocr_result: OCRResult) -> InvoiceExtraction: ...
