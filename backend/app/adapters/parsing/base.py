"""Stable boundary for optional document parsers such as Docling."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedDocument:
    parser: str
    text: str = ""
    page_count: int | None = None
    structure: dict[str, Any] = field(default_factory=dict)


class DocumentParser(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def parse_bytes(self, file_bytes: bytes, filename: str) -> ParsedDocument: ...
