"""OCR service boundary with Paddle primary and Tesseract fallback adapters."""

from app.services.ocr.paddle import PaddleOCREngine, PaddleStructureV3OCREngine
from app.services.ocr.tesseract import TesseractOCR

__all__ = ["PaddleOCREngine", "PaddleStructureV3OCREngine", "TesseractOCR"]
