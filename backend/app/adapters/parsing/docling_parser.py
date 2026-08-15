"""Optional Docling document parser for normalized PDF structure."""

from __future__ import annotations

import asyncio
import json
from io import BytesIO

from app.adapters.parsing.base import DocumentParser, ParsedDocument
from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    from docling.datamodel.base_models import DocumentStream
    from docling.document_converter import DocumentConverter

    DOCLING_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the optional local install
    DocumentStream = None
    DocumentConverter = None
    DOCLING_AVAILABLE = False


class DoclingDocumentParser(DocumentParser):
    """Convert a PDF/image byte stream into a bounded, serializable structure."""

    def __init__(self):
        if not DOCLING_AVAILABLE or DocumentConverter is None or DocumentStream is None:
            raise ImportError("Docling is not installed. Install the local-full extra.")
        self._converter = DocumentConverter()

    @property
    def name(self) -> str:
        return "docling"

    async def parse_bytes(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._parse_sync, file_bytes, filename)

    def _parse_sync(self, file_bytes: bytes, filename: str) -> ParsedDocument:
        stream = DocumentStream(name=filename, stream=BytesIO(file_bytes))
        result = self._converter.convert(stream, raises_on_error=False)
        document = getattr(result, "document", None)
        if document is None:
            raise RuntimeError("Docling returned no document")

        markdown = ""
        export_markdown = getattr(document, "export_to_markdown", None)
        if callable(export_markdown):
            markdown = str(export_markdown() or "")
        if not markdown:
            export_text = getattr(document, "export_to_text", None)
            if callable(export_text):
                markdown = str(export_text() or "")

        structure: dict[str, object] = {
            "parser": self.name,
            "markdown": markdown[:120_000],
        }
        export_dict = getattr(document, "export_to_dict", None)
        if callable(export_dict):
            try:
                exported = export_dict()
                if isinstance(exported, dict):
                    structure["document"] = exported
                    # Validate that the optional export can cross the JSON
                    # extraction boundary before it reaches SQLAlchemy.
                    structure["document"] = json.loads(json.dumps(exported, default=str))
            except Exception as exc:  # pragma: no cover - version-specific export API
                logger.debug("docling_dict_export_skipped", error=str(exc))

        page_count = None
        pages = getattr(document, "pages", None)
        if pages is not None:
            try:
                page_count = len(pages)
            except TypeError:
                page_count = None
        logger.info(
            "docling_parse_complete",
            filename=filename,
            page_count=page_count,
            text_length=len(markdown),
        )
        return ParsedDocument(
            parser=self.name,
            text=markdown,
            page_count=page_count,
            structure=structure,
        )
