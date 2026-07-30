"""Line-item table extraction family."""

from app.adapters.ocr.base import OCRResult
from app.services.extractors.protocol import Extractor


class LineItemExtractor(Extractor):
    """Owns row reconstruction and line arithmetic."""

    def __init__(self, legacy):
        self._legacy = legacy

    def extract(self, ocr_result: OCRResult):
        return self._legacy._extract_line_items(ocr_result.raw_text, ocr_result.lines())
