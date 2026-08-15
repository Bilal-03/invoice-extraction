from datetime import date
from decimal import Decimal

from app.domain.schemas import FieldValue, InvoiceExtraction, TaxDetails, TaxType, VendorDetails
from app.services.ap_service import normalize_text, parse_date
from app.services.validation_service import ValidationService


def test_normalized_business_keys_are_stable():
    assert normalize_text(" ABC Technologies Pvt. Ltd. ") == "abctechnologiespvtltd"
    assert normalize_text("INV/2026-1024") == "inv20261024"


def test_parse_date_handles_indian_invoice_formats():
    assert parse_date("12 Aug 2026") == date(2026, 8, 12)
    assert parse_date("2026-08-12") == date(2026, 8, 12)
    assert parse_date(None) is None


def test_validation_catches_tax_total_mismatch_and_invalid_pan():
    extraction = InvoiceExtraction(
        invoice_number=FieldValue(value="INV-1", confidence=0.9),
        vendor=VendorDetails(
            name=FieldValue(value="ABC", confidence=0.9),
            pan=FieldValue(value="BADPAN", confidence=0.8),
        ),
        subtotal=Decimal("1000"),
        tax_total=Decimal("100"),
        grand_total=Decimal("1100"),
        taxes=[TaxDetails(tax_type=TaxType.CGST_SGST, amount=Decimal("80"))],
    )
    flags = ValidationService().validate(extraction)
    assert any(flag.rule == "pan" and not flag.passed for flag in flags)
    assert any(flag.rule == "tax_total" and not flag.passed for flag in flags)
