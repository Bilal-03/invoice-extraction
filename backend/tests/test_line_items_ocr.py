from decimal import Decimal

from app.adapters.ocr.base import OCRResult, OCRWord
from app.services.field_extractor import FieldExtractor


def _line(text: str, y: int) -> list[OCRWord]:
    words = text.split()
    return [
        OCRWord(
            text=word,
            confidence=0.8,
            x=index * 40,
            y=y,
            width=max(12, len(word) * 8),
            height=12,
        )
        for index, word in enumerate(words)
    ]


def test_noisy_scanned_table_keeps_wrapped_product_description() -> None:
    lines = [
        _line("Invoice Date: 30.03.2018", 100),
        _line("Nokia 2 (Pewter/Black) B07846F3SX", 140),
        _line("Nokia 2 (Pewter/Black) HSN:8517", 155),
        _line("5517.86 1 5517.86 12% IGST 662.14 6180.00", 170),
        _line("Shipping Charges 44.64 0.00 12% IGST 0.00 0.00", 190),
    ]
    ocr = OCRResult(
        raw_text="\n".join(" ".join(word.text for word in row) for row in lines),
        words=[word for row in lines for word in row],
        average_confidence=0.75,
    )

    items = FieldExtractor().extract(ocr).line_items

    assert len(items) == 2
    assert "Nokia 2" in items[0].description
    assert items[0].quantity == Decimal("1")
    assert items[0].unit_price == Decimal("5517.86")
    assert items[0].line_total == Decimal("6180.00")
    assert items[1].description.lower().startswith("shipping charges")
