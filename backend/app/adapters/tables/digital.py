"""Best-effort table extraction for digital PDFs.

The adapter is intentionally optional and ordered from the lowest-friction
local path to heavier fallbacks:

1. PyMuPDF native ``Page.find_tables`` when available.
2. pdfplumber when installed.
3. Camelot when installed and the PDF contains extractable table geometry.

Scanned PDFs do not reach this adapter; PP-StructureV3 supplies their table
structure through ``OCRResult.structured_data``.
"""

from __future__ import annotations

import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def extract_pdf_tables(file_bytes: bytes) -> list[dict[str, Any]]:
    tables = _pymupdf_tables(file_bytes)
    if tables:
        return tables
    tables = _pdfplumber_tables(file_bytes)
    if tables:
        return tables
    return _camelot_tables(file_bytes)


def _pymupdf_tables(file_bytes: bytes) -> list[dict[str, Any]]:
    try:
        import fitz

        document = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        logger.debug("pymupdf_table_adapter_unavailable", error=str(exc))
        return []

    tables: list[dict[str, Any]] = []
    try:
        for page_number, page in enumerate(document):
            finder = getattr(page, "find_tables", None)
            if not callable(finder):
                continue
            try:
                found = finder()
                candidates = getattr(found, "tables", found if isinstance(found, list) else [])
                for table in candidates or []:
                    rows = table.extract() if callable(getattr(table, "extract", None)) else []
                    rows = _clean_rows(rows)
                    if rows:
                        tables.append({"source": "pymupdf", "page": page_number, "rows": rows})
            except Exception as exc:
                logger.debug("pymupdf_table_extraction_failed", page=page_number, error=str(exc))
    finally:
        document.close()
    return tables


def _pdfplumber_tables(file_bytes: bytes) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except Exception:
        return []

    tables: list[dict[str, Any]] = []
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as document:
            for page_number, page in enumerate(document.pages):
                for rows in page.extract_tables() or []:
                    rows = _clean_rows(rows)
                    if rows:
                        tables.append({"source": "pdfplumber", "page": page_number, "rows": rows})
    except Exception as exc:
        logger.debug("pdfplumber_table_extraction_failed", error=str(exc))
    return tables


def _camelot_tables(file_bytes: bytes) -> list[dict[str, Any]]:
    try:
        import camelot
    except Exception:
        return []

    tables: list[dict[str, Any]] = []
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
            temporary.write(file_bytes)
            temporary_path = Path(temporary.name)
        found = camelot.read_pdf(str(temporary_path), pages="all", flavor="stream")
        for table in found:
            rows = _clean_rows(table.data)
            if rows:
                page = int(getattr(table, "page", 1)) - 1
                tables.append({"source": "camelot", "page": page, "rows": rows})
    except Exception as exc:
        logger.debug("camelot_table_extraction_failed", error=str(exc))
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return tables


def _clean_rows(rows: Any) -> list[list[str]]:
    if not isinstance(rows, (list, tuple)):
        return []
    cleaned: list[list[str]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            continue
        values = [" ".join(str(cell or "").split()) for cell in row]
        if any(values):
            cleaned.append(values)
    return cleaned
