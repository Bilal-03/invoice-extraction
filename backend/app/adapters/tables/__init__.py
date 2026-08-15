"""Provider adapters for digital and layout-model invoice tables."""

from app.adapters.tables.digital import extract_pdf_tables

__all__ = ["extract_pdf_tables"]
