import numpy as np
from pytest import approx

from app.adapters.ocr.paddle_structure import normalise_paddle_result
from app.core.database import Base


def test_supabase_schema_contract_uses_requested_table_names_and_columns():
    expected_tables = {
        "users",
        "vendors",
        "invoices",
        "invoice_items",
        "invoice_taxes",
        "purchase_orders",
        "purchase_order_items",
        "goods_receipts",
        "goods_receipt_items",
        "payments",
        "invoice_validations",
        "invoice_flags",
        "ai_extractions",
        "human_corrections",
        "audit_logs",
    }
    assert expected_tables.issubset(Base.metadata.tables)

    invoices = Base.metadata.tables["invoices"].c
    assert {"ocr_text", "cgst", "sgst", "igst", "confidence_score"}.issubset(invoices.keys())

    items = Base.metadata.tables["invoice_items"].c
    assert {"sku", "hsn", "sac", "rate", "tax"}.issubset(items.keys())

    vendors = Base.metadata.tables["vendors"].c
    assert "state" in vendors


def test_paddle_result_normalization_preserves_text_scores_and_boxes():
    image = np.zeros((100, 200), dtype=np.uint8)
    result = normalise_paddle_result(
        {
            "rec_texts": ["Invoice INV-42", "Grand total 118.00"],
            "rec_scores": [0.98, 0.91],
            "rec_boxes": [[10, 10, 100, 25], [10, 50, 150, 65]],
        },
        image,
        "pp-structure-v3",
    )

    assert result.engine_name == "pp-structure-v3"
    assert result.raw_text == "Invoice INV-42\nGrand total 118.00"
    assert [word.text for word in result.words] == [
        "Invoice",
        "INV-42",
        "Grand",
        "total",
        "118.00",
    ]
    assert result.average_confidence == approx(0.938)
    assert result.words[0].bbox == (10, 10, 55, 25)
    assert result.structured_data == {
        "engine": "pp-structure-v3",
        "regions": [
            {"text": "Invoice INV-42", "bbox": [10, 10, 100, 25], "label": "text"},
            {"text": "Grand total 118.00", "bbox": [10, 50, 150, 65], "label": "text"},
        ],
    }
