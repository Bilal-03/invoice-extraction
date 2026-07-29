from decimal import Decimal

from app.domain.schemas import (
    FieldValue,
    InvoiceExtraction,
    LineItem,
    TaxDetails,
    TaxType,
    VendorDetails,
)
from app.services.validation_service import ValidationService


def test_validation_arithmetic():
    service = ValidationService()

    # Valid extraction
    extraction = InvoiceExtraction(
        line_items=[
            LineItem(
                description="Item 1",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                line_total=Decimal("100"),
            ),
            LineItem(
                description="Item 2",
                quantity=Decimal("2"),
                unit_price=Decimal("50"),
                line_total=Decimal("100"),
            ),
        ],
        taxes=[TaxDetails(tax_type=TaxType.GST, amount=Decimal("20"))],
        grand_total=Decimal("220"),
    )

    flag = service._validate_arithmetic(extraction)
    assert flag.passed is True

    # Invalid extraction
    extraction.grand_total = Decimal("200")
    flag = service._validate_arithmetic(extraction)
    assert flag.passed is False
    assert flag.severity == "warning"


def test_validation_gstin():
    service = ValidationService()

    # Valid GSTIN
    extraction = InvoiceExtraction(vendor=VendorDetails(gstin=FieldValue(value="27AAPFU0939F1ZV")))

    flag = service._validate_gstin(extraction)
    assert flag.passed is True

    # Invalid GSTIN format
    extraction.vendor.gstin.value = "INVALID"
    flag = service._validate_gstin(extraction)
    assert flag.passed is False
