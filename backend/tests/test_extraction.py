from decimal import Decimal

from app.adapters.ocr.base import OCRResult, OCRWord
from app.adapters.preprocessing.pipeline import extract_pdf_ocr_result, extract_pdf_text
from app.services.field_extractor import FieldExtractor


def test_extract_invoice_number():
    extractor = FieldExtractor()

    # Test typical format
    result = OCRResult(
        raw_text="Invoice No: INV-2024-00123\nDate: 15/01/2024", words=[], average_confidence=0.9
    )

    val = extractor._extract_invoice_number(result.raw_text, result.words)
    assert val.value == "INV-2024-00123"

    # Test edge case: bill number
    result.raw_text = "BILL NUMBER: 9988776655"
    val = extractor._extract_invoice_number(result.raw_text, result.words)
    assert val.value == "9988776655"

    result.raw_text = "Invoice Number # LBAAAEK270002369"
    val = extractor._extract_invoice_number(result.raw_text, result.words)
    assert val.value == "LBAAAEK270002369"


def test_extract_taxes():
    extractor = FieldExtractor()

    # Test GST
    text = "CGST @ 9% 45.00\nSGST @ 9% 45.00\nTotal 590.00"
    taxes = extractor._extract_taxes(text)

    assert len(taxes) == 1
    assert taxes[0].tax_type == "CGST_SGST"
    assert taxes[0].rate_percent == 9.0

    # Test IGST
    text = "IGST @ 18% 180.00\nTotal 1180.00"
    taxes = extractor._extract_taxes(text)

    assert len(taxes) == 1
    assert taxes[0].tax_type == "IGST"
    assert taxes[0].rate_percent == 18.0


def test_parse_number():
    extractor = FieldExtractor()

    assert extractor._parse_number("1,234.56") == 1234.56
    assert extractor._parse_number("$ 1,234.56") == 1234.56
    assert extractor._parse_number("1234.56") == 1234.56
    assert extractor._parse_number("₹ 500") == 500.0
    assert extractor._parse_number("1.234,56") == 1234.56


def test_due_date_requires_due_date_context():
    extractor = FieldExtractor()
    text = "Invoice Date: 15/01/2024"

    assert extractor._extract_date(text, [], ["due date"], allow_fallback=False) is None
    assert extractor._extract_date(text, [], ["invoice date"]) == "15/01/2024"


def test_line_item_uses_final_amount_and_skips_summary_rows():
    extractor = FieldExtractor()
    text = "Consulting services 2 100.00 10.00 190.00\nTotal 1 190.00 190.00"

    items = extractor._extract_line_items(text, [])

    assert len(items) == 1
    assert items[0].description == "Consulting services"
    assert items[0].quantity == 2
    assert items[0].unit_price == 100
    assert items[0].line_total == 190


def test_amazon_invoice_extracts_all_planned_fields():
    text = """
Order Number: 403-4977229-5761124
Invoice Number : SDEG-171767
Order Date: 06.06.2024
Invoice Date : 07.06.2024
Sl. No Description Unit Price Qty Net Amount Tax Rate Tax Type Tax Amount Total Amount
1 Acer 100 cm (40 inches) Advanced I Series Full HD Smart
LED Google TV AR40GR2841FDFL (Black)
HSN:85287216
₹13,280.47 1 ₹13,280.47 28% IGST ₹3,718.53 ₹16,999.00
TOTAL:
₹3,718.53 ₹16,999.00
Invoice Value:
16,999.00
Sold By :
DAWNTECH ELECTRONICS PRIVATE LIMITED
* B 300, ERPL Warehousing Park Private Limited
Khewat 2/2, Rectangle No 34, Gurgaon, Haryana, 122105
IN
PAN No: AAMCM3175B
GST Registration No: 06AAMCM3175B3ZK
Billing Address :
Mohd Shaad
B-30/1, Okhla Vihar, Jamia Nagar
New Delhi, DELHI, 110025
IN
State/UT Code: 07
Shipping Address :
Mohd Shaad
Shanul Mulk
B-30/1, First Floor, Okhla Vihar, Jamia Nagar
NEW DELHI, DELHI, 110025
IN
State/UT Code: 07
Place of supply: DELHI
"""
    result = FieldExtractor().extract(OCRResult(raw_text=text, words=[], average_confidence=0.99))

    assert result.invoice_number.value == "SDEG-171767"
    assert result.invoice_date == "07.06.2024"
    assert result.due_date is None
    assert result.po_reference.value == "403-4977229-5761124"
    assert result.vendor.name.value == "DAWNTECH ELECTRONICS PRIVATE LIMITED"
    assert "Gurgaon, Haryana, 122105" in result.vendor.address.value
    assert result.vendor.gstin.value == "06AAMCM3175B3ZK"
    assert result.buyer.name.value == "Mohd Shaad"
    assert "Jamia Nagar" in result.buyer.billing_address.value
    assert "First Floor" in result.buyer.shipping_address.value
    assert len(result.line_items) == 1
    assert result.line_items[0].quantity == 1
    assert result.line_items[0].unit_price == Decimal("13280.47")
    assert result.line_items[0].line_total == Decimal("13280.47")
    assert result.taxes[0].tax_type == "IGST"
    assert result.taxes[0].rate_percent == 28
    assert result.tax_total == Decimal("3718.53")
    assert result.subtotal == Decimal("13280.47")
    assert result.grand_total == Decimal("16999")


def test_extract_pdf_text_prefers_embedded_digital_text():
    import fitz

    document = fitz.open()
    page = document.new_page()
    expected = (
        "Invoice Number INV-100 Vendor Example Company Billing Address Buyer Name "
        "Description Consulting services Quantity one Subtotal one hundred Tax total "
        "Grand total payment terms purchase order shipping address currency dollars"
    )
    page.insert_textbox(fitz.Rect(40, 50, 550, 300), expected, fontsize=10)
    pdf_bytes = document.tobytes()
    document.close()

    extracted = extract_pdf_text(pdf_bytes)

    assert extracted is not None
    assert "Invoice Number INV-100" in extracted


def test_native_pdf_ocr_result_keeps_text_and_coordinates():
    import fitz

    document = fitz.open()
    page = document.new_page()
    text = "Invoice Number INV-100 " + "invoice detail " * 20
    page.insert_textbox(fitz.Rect(40, 50, 550, 300), text, fontsize=10)
    result = extract_pdf_ocr_result(document.tobytes())
    document.close()

    assert result is not None
    assert result.engine_name == "pdf_text"
    assert any(word.text == "INV-100" for word in result.words)
    assert result.page_dimensions[0][0] > 0


def test_spatial_columns_keep_vendor_and_buyer_separate_for_scans():
    def word(text: str, x: int, y: int) -> OCRWord:
        return OCRWord(
            text=text, confidence=0.95, x=x, y=y, width=max(20, len(text) * 8), height=12
        )

    words = [
        word("Sold", 50, 20),
        word("By:", 100, 20),
        word("Billing", 620, 20),
        word("Address:", 700, 20),
        word("ACME", 50, 50),
        word("LIMITED", 110, 50),
        word("Jane", 620, 50),
        word("Doe", 680, 50),
        word("1", 50, 80),
        word("Seller", 75, 80),
        word("Street", 140, 80),
        word("2", 620, 80),
        word("Buyer", 645, 80),
        word("Road", 710, 80),
        word("PAN", 50, 110),
        word("No:", 100, 110),
        word("ABCDE1234F", 145, 110),
        word("Shipping", 620, 110),
        word("Address:", 710, 110),
        word("Jane", 620, 140),
        word("Doe", 680, 140),
        word("3", 620, 170),
        word("Ship", 645, 170),
        word("Road", 700, 170),
        word("Place", 620, 200),
        word("of", 680, 200),
        word("supply:", 710, 200),
    ]
    raw_text = """Sold By: Billing Address:
ACME LIMITED Jane Doe
1 Seller Street 2 Buyer Road
PAN No: ABCDE1234F Shipping Address:
Jane Doe
3 Ship Road
Place of supply: DELHI
Invoice Number: INV-1
Grand Total: 100.00"""
    result = FieldExtractor().extract(
        OCRResult(
            raw_text=raw_text,
            words=words,
            average_confidence=0.95,
            page_dimensions={0: (1000, 1000)},
        )
    )

    assert result.vendor.name.value == "ACME LIMITED"
    assert result.vendor.address.value == "1 Seller Street"
    assert result.buyer.name.value == "Jane Doe"
    assert result.buyer.billing_address.value == "2 Buyer Road"
    assert result.buyer.shipping_address.value == "3 Ship Road"
