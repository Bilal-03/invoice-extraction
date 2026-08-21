from decimal import Decimal

from app.domain.schemas import (
    BuyerDetails,
    FieldValue,
    InvoiceExtraction,
    LineItem,
    TaxDetails,
    TaxType,
    VendorDetails,
)
from app.validation.amount_validator import validate_amounts, validate_tax_consistency
from app.validation.date_validator import validate_dates
from app.validation.duplicate_validator import (
    duplicate_fingerprint,
    duplicate_fingerprint_components,
    duplicate_key,
    validate_duplicate,
)
from app.validation.gst_validator import validate_gst_mode
from app.validation.pan_validator import validate_pans


def _extraction(**overrides) -> InvoiceExtraction:
    values = {
        "invoice_number": FieldValue(value="INV-100", confidence=0.9),
        "vendor": VendorDetails(
            name=FieldValue(value="Example Vendor", confidence=0.9),
            gstin=FieldValue(value="27ABCDE1234F1Z5", confidence=0.9),
        ),
        "subtotal": Decimal("10000"),
        "discount_total": Decimal("1000"),
        "tax_total": Decimal("1620"),
        "taxes": [
            TaxDetails(tax_type=TaxType.CGST, amount=Decimal("810")),
            TaxDetails(tax_type=TaxType.SGST, amount=Decimal("810")),
        ],
        "grand_total": Decimal("10620"),
    }
    values.update(overrides)
    return InvoiceExtraction(**values)


def test_amount_validation_reconciles_discount_tax_and_grand_total() -> None:
    passed = validate_amounts(_extraction())[0]
    assert passed.passed is True
    assert "Mathematical validation passed" in passed.message
    assert passed.details["taxable_amount"] == "9000"
    assert passed.details["calculated_total"] == "10620"

    mismatch = validate_amounts(_extraction(grand_total=Decimal("10820")))[0]
    assert mismatch.passed is False
    assert "Calculated: ₹10,620" in mismatch.message
    assert "Invoice: ₹10,820" in mismatch.message
    assert "Difference: ₹200" in mismatch.message
    assert mismatch.details["difference"] == "200"


def test_tax_rows_and_gst_mode_are_automated_consistency_checks() -> None:
    extraction = _extraction(
        buyer=BuyerDetails(
            name=FieldValue(value="Buyer", confidence=0.9),
            gstin=FieldValue(value="29BUYER1234F1Z5", confidence=0.9),
        )
    )
    mode = validate_gst_mode(extraction)
    assert mode.passed is False
    assert "Automated consistency check only" in mode.message
    assert mode.details["expected_mode"] == "IGST"

    tax_flags = validate_tax_consistency(extraction)
    assert any(flag.rule == "tax_total" and flag.passed for flag in tax_flags)


def test_pan_date_and_duplicate_validators_cover_side_checks() -> None:
    extraction = _extraction(
        invoice_date="31/08/2026",
        due_date="01/08/2026",
        vendor=VendorDetails(
            name=FieldValue(value="Example Vendor", confidence=0.9),
            pan=FieldValue(value="ABCDE1234F", confidence=0.9),
        ),
        buyer=BuyerDetails(pan=FieldValue(value="PQRSX5678K", confidence=0.9)),
    )

    pan_flags = validate_pans(extraction)
    assert all(flag.passed for flag in pan_flags)
    date_flags = validate_dates(extraction)
    assert any(flag.rule == "date_order" and not flag.passed for flag in date_flags)
    date_flag = next(flag for flag in date_flags if flag.rule == "date_order")
    assert date_flag.message == "Due date occurs before invoice date"
    assert date_flag.details["difference_days"] == 30

    key = duplicate_key(extraction)
    assert key is not None
    duplicate = validate_duplicate(extraction, [key])
    assert duplicate.passed is False
    assert duplicate.rule == "duplicate_invoice"


def test_duplicate_fingerprint_uses_supplier_number_date_and_total() -> None:
    extraction = _extraction(invoice_date="12 Aug 2026")
    components = duplicate_fingerprint_components(extraction)
    assert components == {
        "supplier_gstin": "27ABCDE1234F1Z5",
        "invoice_number": "inv100",
        "invoice_date": "2026-08-12",
        "grand_total": "10620.00",
    }
    fingerprint = duplicate_fingerprint(extraction)
    assert fingerprint is not None
    assert len(fingerprint) == 64
    assert validate_duplicate(extraction, existing_fingerprints=[fingerprint]).passed is False
    assert duplicate_fingerprint(_extraction(invoice_date="13 Aug 2026")) != fingerprint


def test_amount_validator_can_use_line_items_when_subtotal_is_missing() -> None:
    extraction = _extraction(
        subtotal=None,
        discount_total=Decimal("0"),
        line_items=[
            LineItem(
                description="Service",
                quantity=Decimal("1"),
                unit_price=Decimal("9000"),
                line_total=Decimal("9000"),
                confidence=0.9,
            )
        ],
    )
    flag = validate_amounts(extraction)[0]
    assert flag.passed is True
    assert flag.details["calculated_total"] == "10620"
