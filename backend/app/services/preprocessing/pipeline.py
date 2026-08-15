"""Compatibility facade for the OpenCV/Pillow/PyMuPDF pipeline."""

from app.adapters.preprocessing.pipeline import (
    PreprocessingPipeline,
    PreprocessingResult,
    extract_pdf_ocr_result,
    extract_pdf_text,
    load_image_from_bytes,
    load_pdf_page,
    load_pdf_pages,
)

__all__ = [
    "PreprocessingPipeline",
    "PreprocessingResult",
    "extract_pdf_ocr_result",
    "extract_pdf_text",
    "load_image_from_bytes",
    "load_pdf_page",
    "load_pdf_pages",
]
