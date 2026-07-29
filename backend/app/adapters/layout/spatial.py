"""Deterministic spatial layout extractor available without model downloads."""

from app.adapters.layout.base import LayoutExtractor
from app.adapters.ocr.base import OCRResult
from app.domain.schemas import InvoiceExtraction
from app.services.field_extractor import FieldExtractor


class SpatialLayoutExtractor(LayoutExtractor):
    def __init__(self):
        self._extractor = FieldExtractor()

    @property
    def name(self) -> str:
        return "spatial-rules"

    def extract(self, ocr_result: OCRResult) -> InvoiceExtraction:
        return self._extractor.extract(ocr_result)
