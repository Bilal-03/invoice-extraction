import json
from datetime import date
from decimal import Decimal

import cv2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.routers.ap import list_invoices
from app.core.database import Base
from app.domain.entities import Document, Invoice, Vendor
from app.domain.schemas import (
    FieldValue,
    InvoiceExtraction,
    InvoiceStatus,
    MatchStatus,
    ValidationFlag,
    ValidationSeverity,
    VendorDetails,
)
from app.services.ap_service import _risk_inputs
from app.services.qr_service import compare_qr_with_extraction, detect_qr, parse_qr_payload


def _extraction() -> InvoiceExtraction:
    return InvoiceExtraction(
        invoice_number=FieldValue(value="INV-1024", confidence=0.98),
        invoice_date="2026-08-15",
        vendor=VendorDetails(
            name=FieldValue(value="ABC Technologies", confidence=0.98),
            gstin=FieldValue(value="27ABCDE1234F1Z5", confidence=0.98),
        ),
        subtotal=Decimal("50000"),
        tax_total=Decimal("9000"),
        grand_total=Decimal("59000"),
    )


def test_qr_payload_normalisation_and_field_comparison():
    payload = json.dumps(
        {
            "DocNo": "INV-1024",
            "DocDt": "15/08/2026",
            "SellerGstin": "27abcde1234f1z5",
            "TotTaxableVal": 50000,
            "TotInvVal": "₹59,000.00",
            "Irn": "IRN-LOCAL-1",
            "AckNo": "ACK-1",
        }
    )
    fields = parse_qr_payload(payload)
    assert fields["invoice_number"] == "INV-1024"
    assert fields["seller_gstin"] == "27abcde1234f1z5"
    assert fields["grand_total"] == "₹59,000.00"
    assert fields["irn"] == "IRN-LOCAL-1"

    status, comparisons = compare_qr_with_extraction(fields, _extraction())
    assert status == "match"
    assert comparisons["invoice_number"].status == "match"
    assert comparisons["grand_total"].status == "match"

    mismatch_status, mismatch = compare_qr_with_extraction(
        {**fields, "grand_total": "59001"}, _extraction()
    )
    assert mismatch_status == "mismatch"
    assert mismatch["grand_total"].difference == "1.00"


def test_opencv_detector_decodes_a_document_qr():
    if not hasattr(cv2, "QRCodeEncoder_create"):
        pytest.skip("OpenCV QR encoder is unavailable in this build")
    encoder = cv2.QRCodeEncoder_create()
    image = encoder.encode(json.dumps({"DocNo": "INV-1024", "TotInvVal": 59000}))
    image = cv2.copyMakeBorder(image, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    image = cv2.resize(image, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)

    result = detect_qr(image)

    assert result["qr_detected"] is True
    assert result["qr_fields"]["invoice_number"] == "INV-1024"
    assert result["qr_fields"]["grand_total"] == "59000"


def test_qr_mismatch_is_a_fixed_risk_contribution():
    flags = [
        ValidationFlag(
            rule="qr_ocr_mismatch",
            passed=False,
            message="QR total differs from OCR total",
            severity=ValidationSeverity.WARNING,
            details={"field": "grand_total", "difference": "1.00"},
        )
    ]

    risk_flags = _risk_inputs(
        _extraction(),
        flags,
        new_vendor=False,
        duplicate=False,
        match_status=MatchStatus.NOT_APPLICABLE,
    )

    assert risk_flags == [
        (
            "qr_ocr_mismatch",
            15,
            "QR total differs from OCR total",
            {"field": "grand_total", "difference": "1.00"},
        )
    ]


@pytest.mark.asyncio
async def test_invoice_search_covers_business_fields():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        vendor = Vendor(
            tenant_id="local",
            name="ABC Technologies",
            normalized_name="abctechnologies",
            gstin="27ABCDE1234F1Z5",
        )
        other_vendor = Vendor(
            tenant_id="local",
            name="Other Supplier",
            normalized_name="othersupplier",
            gstin="29ABCDE5678G1Z2",
        )
        session.add_all([vendor, other_vendor])
        await session.flush()
        document = Document(
            tenant_id="local",
            filename="target.pdf",
            original_filename="target.pdf",
            file_path="target.pdf",
            status="completed",
        )
        other_document = Document(
            tenant_id="local",
            filename="other.pdf",
            original_filename="other.pdf",
            file_path="other.pdf",
            status="completed",
        )
        session.add_all([document, other_document])
        await session.flush()
        session.add_all(
            [
                Invoice(
                    tenant_id="local",
                    document_id=document.id,
                    vendor_id=vendor.id,
                    invoice_number="INV-1024",
                    normalized_invoice_number="inv1024",
                    invoice_date=date(2026, 8, 15),
                    due_date=date(2026, 9, 14),
                    po_number="PO-1024",
                    grand_total=Decimal("50000"),
                    outstanding_amount=Decimal("50000"),
                    status=InvoiceStatus.APPROVED.value,
                    match_status="not_applicable",
                ),
                Invoice(
                    tenant_id="local",
                    document_id=other_document.id,
                    vendor_id=other_vendor.id,
                    invoice_number="OTHER-1",
                    normalized_invoice_number="other1",
                    invoice_date=date(2026, 8, 16),
                    due_date=date(2026, 9, 15),
                    po_number="PO-9",
                    grand_total=Decimal("70000"),
                    outstanding_amount=Decimal("70000"),
                    status=InvoiceStatus.REVIEW_REQUIRED.value,
                    match_status="not_applicable",
                ),
            ]
        )
        await session.flush()

        async def search(term: str):
            return await list_invoices(
                page=1,
                page_size=25,
                search=term,
                status_filter=None,
                risk=None,
                vendor_id=None,
                overdue=False,
                date_from=None,
                date_to=None,
                min_amount=None,
                max_amount=None,
                db=session,
                tenant_id="local",
            )

        for term in (
            "ABC Technologies",
            "INV-1024",
            "GSTIN 27ABCDE1234F1Z5",
            "₹50,000",
            "PO-1024",
            "15 Aug 2026",
            "approved",
        ):
            result = await search(term)
            assert result.total == 1, term
            assert result.invoices[0].invoice_number == "INV-1024"

        status_result = await list_invoices(
            page=1,
            page_size=25,
            search=None,
            status_filter="approved",
            risk=None,
            vendor_id=None,
            overdue=False,
            date_from=None,
            date_to=None,
            min_amount=None,
            max_amount=None,
            db=session,
            tenant_id="local",
        )
        assert status_result.total == 1

        invoice_ids = list(await session.scalars(select(Invoice.id)))
        assert len(invoice_ids) == 2

    await engine.dispose()
