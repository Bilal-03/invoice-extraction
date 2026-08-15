"""Line-item table rule family."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

from app.adapters.ocr.base import OCRResult
from app.domain.schemas import LineItem


def extract_line_items(result: OCRResult, legacy_extractor: Any):
    """Extract structured tables first, then fall back to OCR row heuristics."""

    structured_items = extract_structured_line_items(result.structured_data)
    if structured_items:
        return structured_items

    return legacy_extractor._extract_line_items(result.raw_text, result.all_lines())


def extract_structured_line_items(structure: dict[str, Any] | None) -> list[LineItem]:
    """Normalize table rows from PyMuPDF, pdfplumber, Docling, or Paddle.

    The adapters deliberately expose a small interchangeable shape: a table
    may contain ``rows``/``data`` or an HTML representation.  This normalizer
    keeps the extraction schema independent of the selected PDF/OCR provider.
    """

    for rows in _table_rows(structure):
        items = _rows_to_items(rows)
        if items:
            return items
    return []


def _table_rows(value: Any):
    if isinstance(value, dict):
        html = value.get("html") or value.get("pred_html")
        if isinstance(html, str) and "<table" in html.lower():
            rows = _html_rows(html)
            if rows:
                yield rows

        for key in ("table_cells", "cells"):
            rows = _docling_cell_rows(value.get(key), value)
            if rows:
                yield rows

        for key in ("rows", "data", "table_data", "table_rows"):
            candidate = value.get(key)
            if _is_row_matrix(candidate):
                yield candidate
            elif isinstance(candidate, dict):
                yield from _table_rows(candidate)

        for key, candidate in value.items():
            if key in {
                "rows",
                "data",
                "table_data",
                "table_rows",
                "html",
                "pred_html",
                "table_cells",
                "cells",
            }:
                continue
            yield from _table_rows(candidate)
    elif isinstance(value, list):
        for candidate in value:
            yield from _table_rows(candidate)


def _is_row_matrix(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    if all(isinstance(row, dict) for row in value):
        return True
    return all(isinstance(row, (list, tuple)) for row in value)


def _docling_cell_rows(cells: Any, table: dict[str, Any]) -> list[list[str]]:
    """Rebuild a matrix from Docling's positional ``table_cells`` export."""

    if (
        not isinstance(cells, list)
        or not cells
        or not all(isinstance(cell, dict) for cell in cells)
    ):
        return []

    num_rows = _integer(table.get("num_rows"))
    num_cols = _integer(table.get("num_cols"))
    placements: list[tuple[int, int, int, int, str]] = []
    for index, cell in enumerate(cells):
        row = _cell_index(cell, "start_row_offset_idx", "row_index", "row_idx", "row")
        col = _cell_index(cell, "start_col_offset_idx", "col_index", "col_idx", "col")
        if row is None or col is None:
            if not num_cols:
                return []
            row, col = divmod(index, num_cols)

        end_row = _cell_index(cell, "end_row_offset_idx", "end_row")
        end_col = _cell_index(cell, "end_col_offset_idx", "end_col")
        row_span = _integer(cell.get("row_span")) or 1
        col_span = _integer(cell.get("col_span")) or 1
        if end_row is not None:
            row_span = max(row_span, end_row - row + 1)
        if end_col is not None:
            col_span = max(col_span, end_col - col + 1)

        raw_text = cell.get("text")
        if raw_text is None:
            raw_text = cell.get("content")
        if raw_text is None:
            raw_text = cell.get("label")
        if isinstance(raw_text, dict):
            raw_text = raw_text.get("text") or raw_text.get("value")
        placements.append((row, col, row_span, col_span, _clean_cell(raw_text)))

    row_count = max(num_rows or 0, max(row + row_span for row, _, row_span, _, _ in placements))
    col_count = max(num_cols or 0, max(col + col_span for _, col, _, col_span, _ in placements))
    matrix = [["" for _ in range(col_count)] for _ in range(row_count)]
    for row, col, row_span, col_span, text in placements:
        for row_offset in range(row_span):
            for col_offset in range(col_span):
                target_row = row + row_offset
                target_col = col + col_offset
                if (
                    target_row < row_count
                    and target_col < col_count
                    and not matrix[target_row][target_col]
                ):
                    matrix[target_row][target_col] = text
    return matrix


def _cell_index(cell: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _integer(cell.get(key))
        if value is not None:
            return value
    return None


def _integer(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(_clean_cell(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None


def _html_rows(html: str) -> list[list[str]]:
    parser = _HTMLTableParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    return parser.rows


def _rows_to_items(rows: list[Any]) -> list[LineItem]:
    if not rows:
        return []
    if all(isinstance(row, dict) for row in rows):
        items: list[LineItem] = []
        for row in rows:
            item = _dict_to_item(row)
            if item is not None:
                items.append(item)
        return items

    header_index = _find_header_index(rows)
    headers = rows[header_index] if header_index is not None else []
    mapped_headers = [_header_key(str(header)) for header in headers]
    data_rows = rows[header_index + 1 :] if header_index is not None else rows
    items: list[LineItem] = []
    for row in data_rows:
        if not isinstance(row, (list, tuple)):
            continue
        values = {
            mapped_headers[index]: cell
            for index, cell in enumerate(row)
            if index < len(mapped_headers) and mapped_headers[index]
        }
        item = _values_to_item(values)
        if item is not None:
            items.append(item)
    return items


def _dict_to_item(row: dict[str, Any]) -> LineItem | None:
    values: dict[str, Any] = {}
    for key, value in row.items():
        canonical = _header_key(str(key))
        if canonical:
            values[canonical] = value
    return _values_to_item(values)


def _find_header_index(rows: list[Any]) -> int | None:
    for index, row in enumerate(rows[:6]):
        if not isinstance(row, (list, tuple)):
            continue
        recognized = sum(1 for cell in row if _header_key(str(cell)))
        if recognized >= 2:
            return index
    return None


def _header_key(value: str) -> str | None:
    key = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    if not key:
        return None
    if any(label in key for label in ("description", "particular", "product", "item", "service")):
        return "description"
    if "hsn" in key or "sac" in key:
        return "hsn_sac"
    if "quantity" in key or re.search(r"\bqty\b|\bqnty\b", key):
        return "quantity"
    if "gst" in key or "tax rate" in key or "tax %" in key:
        return "gst_rate" if "amount" not in key else "tax_amount"
    if "unit price" in key or "unit rate" in key or key in {"rate", "price"}:
        return "unit_price"
    if "tax amount" in key:
        return "tax_amount"
    if any(label in key for label in ("amount", "line total", "total", "value")):
        return "line_total"
    if "discount" in key:
        return "discount"
    return None


def _values_to_item(values: dict[str, Any]) -> LineItem | None:
    description = _clean_cell(values.get("description"))
    if not description or _is_summary(description):
        return None
    quantity = _decimal(values.get("quantity"))
    unit_price = _decimal(values.get("unit_price"))
    line_total = _decimal(values.get("line_total"))
    if line_total is None and quantity is not None and unit_price is not None:
        line_total = quantity * unit_price
    if quantity is None and unit_price is None and line_total is None:
        return None
    hsn = _clean_hsn(values.get("hsn_sac"))
    gst_rate = _percent(values.get("gst_rate"))
    tax_amount = _decimal(values.get("tax_amount")) or Decimal("0")
    discount = _decimal(values.get("discount")) or Decimal("0")
    observed = sum(value is not None for value in (quantity, unit_price, line_total, hsn, gst_rate))
    confidence = min(0.98, 0.45 + observed * 0.1)
    return LineItem(
        description=description,
        hsn_sac=hsn,
        quantity=quantity or Decimal("0"),
        unit_price=unit_price or Decimal("0"),
        gst_rate=gst_rate,
        tax_amount=tax_amount,
        discount=discount,
        line_total=line_total or Decimal("0"),
        confidence=confidence,
    )


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^0-9,.-]", "", str(value).replace("\u00a0", ""))
    if not cleaned or cleaned in {".", "-", ","}:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = (
            cleaned.replace(".", "").replace(",", ".")
            if cleaned.rfind(",") > cleaned.rfind(".")
            else cleaned.replace(",", "")
        )
    elif "," in cleaned:
        tail = cleaned.rsplit(",", 1)[1]
        cleaned = cleaned.replace(",", ".") if len(tail) == 2 else cleaned.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _percent(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(value))
    return _decimal(match.group(1)) if match else None


def _clean_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_hsn(value: Any) -> str | None:
    cleaned = _clean_cell(value)
    if not cleaned:
        return None
    if re.fullmatch(r"\d+\.0+", cleaned):
        return cleaned.split(".", 1)[0]
    return cleaned


def _is_summary(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?i)(?:sub\s*total|grand\s*total|total|tax|taxable amount|"
            r"amount due|balance due|round(?:ing)? off)",
            value,
        )
    )
