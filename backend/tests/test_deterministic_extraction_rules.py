from app.adapters.ocr.base import OCRResult, OCRWord
from app.domain.schemas import ExtractionSource, OCRTokenResponse
from app.extraction.context import RuleContext
from app.extraction.gst import extract_gstin, is_valid_gstin_syntax, normalize_gstin
from app.extraction.invoice_date import extract_dates
from app.extraction.invoice_number import extract_invoice_number
from app.extraction.line_items import extract_structured_line_items
from app.extraction.pan import extract_pan, extract_party_pans
from app.services.field_extractor import FieldExtractor
from app.services.validation_service import ValidationService


def _ocr_line(text: str, y: int, *, page: int = 0, x: int = 40) -> list[OCRWord]:
    words = text.split()
    result: list[OCRWord] = []
    cursor = x
    for word in words:
        width = max(20, len(word) * 9)
        result.append(
            OCRWord(
                text=word,
                confidence=0.97,
                x=cursor,
                y=y,
                width=width,
                height=24,
                page=page,
            )
        )
        cursor += width + 12
    return result


def test_rule_pipeline_extracts_label_near_fields_with_layout_evidence() -> None:
    rows = [
        _ocr_line("Tax Invoice No: INV-2026-3321", 80),
        _ocr_line("Invoice Date: 15/08/2026", 120),
        _ocr_line("Due Date: 30/08/2026", 160),
        _ocr_line("Sold By: ABC LTD", 220),
        _ocr_line("GSTIN: 27abcde1234f1z5", 260, x=650),
        _ocr_line("PAN: abcde1234f", 300, x=650),
        _ocr_line("Grand Total: ₹ 1,200.00", 360, x=650),
    ]
    result = OCRResult(
        raw_text="\n".join(" ".join(word.text for word in row) for row in rows),
        words=[word for row in rows for word in row],
        average_confidence=0.97,
        page_count=1,
        page_dimensions={0: (1000, 1400)},
    )

    extraction = FieldExtractor().extract(result)

    assert extraction.invoice_number.value == "INV-2026-3321"
    assert extraction.invoice_number.source == ExtractionSource.OCR_RULE
    assert extraction.invoice_number.bounding_box is not None
    assert extraction.invoice_number.bounding_box.page == 0
    assert extraction.invoice_number.bounding_box.x0 > 0.15
    assert extraction.invoice_date == "15/08/2026"
    assert extraction.due_date == "30/08/2026"
    assert extraction.vendor.gstin is not None
    assert extraction.vendor.gstin.value == "27ABCDE1234F1Z5"
    assert extraction.vendor.gstin.source == ExtractionSource.OCR_RULE
    assert extraction.vendor.gstin.bounding_box is not None
    assert extraction.vendor.pan is not None
    assert extraction.vendor.pan.value == "ABCDE1234F"
    assert extraction.vendor.pan.source == ExtractionSource.OCR_RULE

    flags = ValidationService().validate(extraction)
    gstin_flag = next(flag for flag in flags if flag.rule == "gstin")
    assert "27ABCDE1234F1Z5" in gstin_flag.message


def test_gstin_normalization_and_syntax_are_local_and_provider_free() -> None:
    normalized = normalize_gstin("27abcde1234f1z5")

    assert normalized == "27ABCDE1234F1Z5"
    assert is_valid_gstin_syntax(normalized)
    assert not is_valid_gstin_syntax("27ABCDE1234F1Z")


def test_rules_keep_working_for_native_pdf_text_without_word_boxes() -> None:
    result = OCRResult(
        raw_text=(
            "Reference No: REF-2026-99\n"
            "Invoice Date: 15/08/2026\n"
            "Due Date: 30/08/2026\n"
            "GSTIN: 27abcde1234f1z5\n"
            "PAN: abcde1234f"
        ),
        words=[],
        page_count=1,
    )

    assert extract_invoice_number(result).value == "REF-2026-99"
    assert extract_dates(result) == {
        "invoice_date": "15/08/2026",
        "due_date": "30/08/2026",
    }
    assert extract_gstin(result).value == "27ABCDE1234F1Z5"
    assert extract_pan(result).value == "ABCDE1234F"


def test_layout_context_unions_split_tokens_and_preserves_page() -> None:
    words = _ocr_line("INV-2026-3321", 100, page=1, x=420)
    result = OCRResult(
        raw_text="INV-2026-3321",
        words=words,
        page_count=2,
        page_dimensions={1: (1000, 1400)},
    )

    bbox = RuleContext(result).bounding_box("INV-2026-3321")

    assert bbox is not None
    assert bbox.page == 1
    assert bbox.x0 == 0.42
    assert bbox.x1 > bbox.x0


def test_pan_classifier_distinguishes_seller_and_buyer_by_context_and_position() -> None:
    rows = [
        _ocr_line("Sold By: Seller Corp", 80, x=40),
        _ocr_line("Bill To: Buyer Corp", 80, x=600),
        _ocr_line("PAN: ABCDE1234F", 140, x=40),
        _ocr_line("PAN: PQRSX5678K", 140, x=600),
    ]
    result = OCRResult(
        raw_text="\n".join(" ".join(word.text for word in row) for row in rows),
        words=[word for row in rows for word in row],
        average_confidence=0.96,
        page_count=1,
        page_dimensions={0: (1000, 1400)},
    )

    seller_pan, buyer_pan = extract_party_pans(result)

    assert seller_pan is not None
    assert seller_pan.value == "ABCDE1234F"
    assert buyer_pan is not None
    assert buyer_pan.value == "PQRSX5678K"
    assert extract_pan(result).value == "ABCDE1234F"

    extraction = FieldExtractor().extract(result)
    assert extraction.vendor.pan is not None
    assert extraction.vendor.pan.value == "ABCDE1234F"
    assert extraction.buyer is not None
    assert extraction.buyer.pan is not None
    assert extraction.buyer.pan.value == "PQRSX5678K"
    assert extraction.buyer.name is not None
    assert extraction.buyer.name.value == "Buyer Corp"


def test_structured_table_rows_normalize_hsn_rate_gst_and_amount() -> None:
    structure = {
        "tables": [
            {
                "source": "pymupdf",
                "rows": [
                    ["Description", "HSN", "Qty", "Rate", "GST", "Amount"],
                    ["Laptop", "8471", "2", "₹50,000", "18%", "₹100,000"],
                    ["Mouse", "8471", "5", "₹500", "18%", "₹2,500"],
                ],
            }
        ]
    }

    items = extract_structured_line_items(structure)

    assert [(item.description, item.hsn_sac) for item in items] == [
        ("Laptop", "8471"),
        ("Mouse", "8471"),
    ]
    assert items[0].quantity == 2
    assert items[0].unit_price == 50000
    assert items[0].gst_rate == 18
    assert items[0].line_total == 100000
    assert items[1].quantity == 5
    assert items[1].unit_price == 500
    assert items[1].line_total == 2500


def test_structured_html_table_is_supported_for_pp_structure_and_docling() -> None:
    structure = {
        "tables": [
            {
                "html": (
                    "<table><tr><th>Description</th><th>HSN</th><th>Qty</th>"
                    "<th>Rate</th><th>GST</th><th>Amount</th></tr>"
                    "<tr><td>Keyboard</td><td>8471</td><td>1</td><td>1,000</td>"
                    "<td>18%</td><td>1,000</td></tr></table>"
                )
            }
        ]
    }

    items = extract_structured_line_items(structure)

    assert len(items) == 1
    assert items[0].description == "Keyboard"
    assert items[0].hsn_sac == "8471"
    assert items[0].gst_rate == 18
    assert items[0].line_total == 1000


def test_docling_table_cells_are_rebuilt_into_normalized_line_items() -> None:
    structure = {
        "document": {
            "tables": [
                {
                    "data": {
                        "num_rows": 2,
                        "num_cols": 6,
                        "table_cells": [
                            {"row": 0, "col": 0, "text": "Description"},
                            {"row": 0, "col": 1, "text": "HSN"},
                            {"row": 0, "col": 2, "text": "Qty"},
                            {"row": 0, "col": 3, "text": "Rate"},
                            {"row": 0, "col": 4, "text": "GST"},
                            {"row": 0, "col": 5, "text": "Amount"},
                            {"row": 1, "col": 0, "text": "Monitor"},
                            {"row": 1, "col": 1, "text": "8528"},
                            {"row": 1, "col": 2, "text": "2"},
                            {"row": 1, "col": 3, "text": "15000"},
                            {"row": 1, "col": 4, "text": "18%"},
                            {"row": 1, "col": 5, "text": "30000"},
                        ],
                    }
                }
            ]
        }
    }

    items = extract_structured_line_items(structure)

    assert len(items) == 1
    assert items[0].description == "Monitor"
    assert items[0].hsn_sac == "8528"
    assert items[0].quantity == 2
    assert items[0].unit_price == 15000
    assert items[0].gst_rate == 18
    assert items[0].line_total == 30000


def test_ocr_token_contract_exposes_an_explicit_bbox() -> None:
    token = OCRTokenResponse(
        id="token-1",
        document_id="document-1",
        page=0,
        text="INV-1",
        confidence=0.98,
        x=10,
        y=20,
        width=50,
        height=15,
        page_width=1000,
        page_height=1400,
    )

    assert token.model_dump(mode="json")["bbox"] == [10, 20, 60, 35]
