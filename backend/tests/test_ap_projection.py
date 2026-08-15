from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.domain.entities import (
    Document,
    GoodsReceipt,
    GoodsReceiptItem,
    InvoiceRiskFlag,
    InvoiceValidation,
    PurchaseOrder,
    PurchaseOrderItem,
    Vendor,
    WorkflowEvent,
)
from app.domain.schemas import (
    FieldValue,
    InvoiceExtraction,
    InvoiceStatus,
    LineItem,
    TaxDetails,
    TaxType,
    VendorDetails,
    WorkflowAction,
)
from app.services.ap_service import (
    WorkflowError,
    apply_workflow_action,
    dashboard_summary,
    project_document,
    record_payment,
)


def _extraction(number: str | None = "INV-TEST") -> InvoiceExtraction:
    return InvoiceExtraction(
        invoice_number=FieldValue(value=number, confidence=0.96),
        invoice_date="2026-08-01",
        due_date="2026-08-31",
        vendor=VendorDetails(name=FieldValue(value="Test Supplier", confidence=0.96)),
        line_items=[
            LineItem(
                description="Consulting",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                line_total=Decimal("100"),
                confidence=0.9,
            )
        ],
        taxes=[TaxDetails(tax_type=TaxType.IGST, rate_percent=18, amount=Decimal("18"))],
        subtotal=Decimal("100"),
        tax_total=Decimal("18"),
        grand_total=Decimal("118"),
        overall_confidence=0.92,
    )


def _po_extraction(
    *,
    invoice_number: str,
    po_number: str,
    quantity: Decimal,
    grand_total: Decimal,
) -> InvoiceExtraction:
    return InvoiceExtraction(
        invoice_number=FieldValue(value=invoice_number, confidence=0.96),
        invoice_date="2026-08-01",
        due_date="2026-08-31",
        po_reference=FieldValue(value=po_number, confidence=0.96),
        vendor=VendorDetails(
            name=FieldValue(value="ABC Technologies", confidence=0.96),
            gstin=FieldValue(value="27ABCDE1234F1Z5", confidence=0.96),
        ),
        line_items=[
            LineItem(
                description="Keyboard",
                quantity=quantity,
                unit_price=Decimal("1500"),
                line_total=quantity * Decimal("1500"),
                confidence=0.95,
            )
        ],
        subtotal=grand_total,
        tax_total=Decimal("0"),
        grand_total=grand_total,
        overall_confidence=0.95,
    )


async def _session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_projection_workflow_and_partial_payments():
    engine, session_factory = await _session()
    async with session_factory() as session:
        extraction = _extraction()
        document = Document(
            tenant_id="local",
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="test.pdf",
            status="completed",
            extraction_result=extraction.model_dump(mode="json"),
        )
        session.add(document)
        await session.flush()
        invoice = await project_document(session, document)
        assert invoice is not None
        assert invoice.status == InvoiceStatus.REVIEW_REQUIRED.value
        assert invoice.outstanding_amount == Decimal("118.00")

        await apply_workflow_action(session, invoice, WorkflowAction.APPROVE, actor="tester")
        await apply_workflow_action(session, invoice, WorkflowAction.QUEUE_PAYMENT, actor="tester")
        await record_payment(
            session,
            invoice,
            amount=Decimal("59"),
            payment_date=invoice.invoice_date,
            method="bank_transfer",
            reference="PART-1",
            notes=None,
            actor="tester",
        )
        assert invoice.status == InvoiceStatus.AWAITING_PAYMENT.value
        assert invoice.outstanding_amount == Decimal("59.00")
        await record_payment(
            session,
            invoice,
            amount=Decimal("59"),
            payment_date=invoice.invoice_date,
            method="bank_transfer",
            reference="PART-2",
            notes=None,
            actor="tester",
        )
        assert invoice.status == InvoiceStatus.PAID.value
        assert invoice.outstanding_amount == Decimal("0.00")
    await engine.dispose()


async def test_approval_guard_and_later_duplicate_detection():
    engine, session_factory = await _session()
    async with session_factory() as session:
        first = Document(
            tenant_id="local",
            filename="first.pdf",
            original_filename="first.pdf",
            file_path="first.pdf",
            status="completed",
            extraction_result=_extraction().model_dump(mode="json"),
        )
        blocked = _extraction(number=None)
        second = Document(
            tenant_id="local",
            filename="second.pdf",
            original_filename="second.pdf",
            file_path="second.pdf",
            status="completed",
            extraction_result=blocked.model_dump(mode="json"),
        )
        duplicate = Document(
            tenant_id="local",
            filename="duplicate.pdf",
            original_filename="duplicate.pdf",
            file_path="duplicate.pdf",
            status="completed",
            extraction_result=_extraction().model_dump(mode="json"),
        )
        session.add(first)
        await session.flush()
        first_invoice = await project_document(session, first)
        session.add(second)
        await session.flush()
        blocked_invoice = await project_document(session, second)
        session.add(duplicate)
        await session.flush()
        duplicate_invoice = await project_document(session, duplicate)
        assert (
            first_invoice is not None
            and blocked_invoice is not None
            and duplicate_invoice is not None
        )
        assert duplicate_invoice.status == InvoiceStatus.DUPLICATE.value
        try:
            await apply_workflow_action(session, blocked_invoice, WorkflowAction.APPROVE)
        except WorkflowError:
            pass
        else:
            raise AssertionError("missing required fields must block approval")
    await engine.dispose()


async def test_fingerprint_duplicate_evidence_and_vendor_upsert():
    engine, session_factory = await _session()
    async with session_factory() as session:
        first_extraction = _extraction().model_copy(
            update={
                "vendor": VendorDetails(
                    name=FieldValue(value="ABC Technologies Pvt Ltd", confidence=0.96),
                    gstin=FieldValue(value="27abcde1234f1z5", confidence=0.96),
                    email=FieldValue(value="ap@abc.example", confidence=0.9),
                    phone=FieldValue(value="9876543210", confidence=0.9),
                    bank_name=FieldValue(value="Example Bank", confidence=0.9),
                    ifsc=FieldValue(value="EXAM0001234", confidence=0.9),
                )
            }
        )
        first = Document(
            tenant_id="local",
            filename="fingerprint-first.pdf",
            original_filename="fingerprint-first.pdf",
            file_path="fingerprint-first.pdf",
            status="completed",
            extraction_result=first_extraction.model_dump(mode="json"),
        )
        session.add(first)
        await session.flush()
        first_invoice = await project_document(session, first)
        assert first_invoice is not None
        assert first_invoice.duplicate_fingerprint is not None

        second_extraction = first_extraction.model_copy(
            update={
                "vendor": VendorDetails(
                    name=FieldValue(value="ABC Technologies Limited", confidence=0.96),
                    gstin=FieldValue(value="27ABCDE1234F1Z5", confidence=0.96),
                )
            }
        )
        second = Document(
            tenant_id="local",
            filename="fingerprint-duplicate.pdf",
            original_filename="fingerprint-duplicate.pdf",
            file_path="fingerprint-duplicate.pdf",
            status="completed",
            extraction_result=second_extraction.model_dump(mode="json"),
        )
        session.add(second)
        await session.flush()
        duplicate_invoice = await project_document(session, second)
        assert duplicate_invoice is not None
        assert duplicate_invoice.status == InvoiceStatus.DUPLICATE.value
        assert duplicate_invoice.vendor_id == first_invoice.vendor_id

        vendor = await session.scalar(select(Vendor).where(Vendor.id == first_invoice.vendor_id))
        assert vendor is not None
        assert vendor.gstin == "27ABCDE1234F1Z5"
        assert vendor.email == "ap@abc.example"
        assert vendor.phone == "9876543210"
        assert vendor.bank_name == "Example Bank"
        assert vendor.ifsc == "EXAM0001234"

        duplicate_validation = await session.scalar(
            select(InvoiceValidation)
            .where(
                InvoiceValidation.invoice_id == duplicate_invoice.id,
                InvoiceValidation.rule == "duplicate_invoice",
                InvoiceValidation.passed.is_(False),
            )
            .limit(1)
        )
        assert duplicate_validation is not None
        assert duplicate_validation.details["match_type"] == "sha256_fingerprint"
        assert duplicate_validation.details["previously_uploaded"] == "2026-08-01"
        assert duplicate_validation.details["amount"] == "118.00"
        assert "Possible Duplicate Invoice" in duplicate_validation.message

        changed_total = first_extraction.model_copy(update={"grand_total": Decimal("119")})
        third = Document(
            tenant_id="local",
            filename="fingerprint-different-total.pdf",
            original_filename="fingerprint-different-total.pdf",
            file_path="fingerprint-different-total.pdf",
            status="completed",
            extraction_result=changed_total.model_dump(mode="json"),
        )
        session.add(third)
        await session.flush()
        changed_invoice = await project_document(session, third)
        assert changed_invoice is not None
        assert changed_invoice.status == InvoiceStatus.REVIEW_REQUIRED.value

    await engine.dispose()


async def test_risk_score_explains_vendor_changes_amount_anomalies_and_reused_numbers():
    engine, session_factory = await _session()
    async with session_factory() as session:
        first_extraction = _extraction(number="INV-RISK-1").model_copy(
            update={
                "vendor": VendorDetails(
                    name=FieldValue(value="Risky Supplier", confidence=0.96),
                    gstin=FieldValue(value="27ABCDE1234F1Z5", confidence=0.96),
                    bank_name=FieldValue(value="Trusted Bank", confidence=0.96),
                    bank_account=FieldValue(value="111122223333", confidence=0.96),
                    ifsc=FieldValue(value="TRUS0001234", confidence=0.96),
                )
            }
        )
        first_document = Document(
            tenant_id="local",
            filename="risk-first.pdf",
            original_filename="risk-first.pdf",
            file_path="risk-first.pdf",
            status="completed",
            extraction_result=first_extraction.model_dump(mode="json"),
        )
        session.add(first_document)
        await session.flush()
        first_invoice = await project_document(session, first_document)
        assert first_invoice is not None
        first_flags = list(
            await session.scalars(
                select(InvoiceRiskFlag).where(InvoiceRiskFlag.invoice_id == first_invoice.id)
            )
        )
        assert any(flag.code == "unknown_vendor" and flag.points == 15 for flag in first_flags)

        second_extraction = _extraction(number="INV-RISK-2").model_copy(
            update={
                "invoice_date": "2026-08-10",
                "due_date": "2026-08-01",
                "vendor": VendorDetails(
                    name=FieldValue(value="Risky Supplier", confidence=0.96),
                    gstin=FieldValue(value="29ABCDE5678G1Z2", confidence=0.96),
                    bank_name=FieldValue(value="Trusted Bank", confidence=0.96),
                    bank_account=FieldValue(value="999988887777", confidence=0.96),
                    ifsc=FieldValue(value="CHNG0005678", confidence=0.96),
                ),
                "grand_total": Decimal("1000000"),
            }
        )
        second_document = Document(
            tenant_id="local",
            filename="risk-second.pdf",
            original_filename="risk-second.pdf",
            file_path="risk-second.pdf",
            status="completed",
            extraction_result=second_extraction.model_dump(mode="json"),
        )
        session.add(second_document)
        await session.flush()
        second_invoice = await project_document(session, second_document)
        assert second_invoice is not None
        second_flags = list(
            await session.scalars(
                select(InvoiceRiskFlag).where(InvoiceRiskFlag.invoice_id == second_invoice.id)
            )
        )
        second_codes = {flag.code for flag in second_flags}
        assert {
            "gstin_mismatch",
            "bank_details_changed",
            "amount_anomaly",
            "large_purchase",
            "arithmetic",
            "date_order",
        }.issubset(second_codes)
        assert second_invoice.risk_score == min(100, sum(flag.points for flag in second_flags))
        assert second_invoice.risk_level == "high"
        amount_flag = next(flag for flag in second_flags if flag.code == "amount_anomaly")
        assert amount_flag.details["historical_average"] == "118.00"
        bank_flag = next(flag for flag in second_flags if flag.code == "bank_details_changed")
        assert bank_flag.details["bank_account"]["vendor_master"] == "111122223333"

        vendor = await session.scalar(select(Vendor).where(Vendor.id == first_invoice.vendor_id))
        assert vendor is not None
        assert vendor.gstin == "27ABCDE1234F1Z5"
        assert vendor.bank_account == "111122223333"
        assert vendor.ifsc == "TRUS0001234"

        repeated_extraction = _extraction(number="INV-RISK-2").model_copy(
            update={
                "invoice_date": "2026-08-11",
                "vendor": VendorDetails(
                    name=FieldValue(value="Risky Supplier", confidence=0.96),
                    gstin=FieldValue(value="27ABCDE1234F1Z5", confidence=0.96),
                ),
                "grand_total": Decimal("120"),
            }
        )
        repeated_document = Document(
            tenant_id="local",
            filename="risk-repeated-number.pdf",
            original_filename="risk-repeated-number.pdf",
            file_path="risk-repeated-number.pdf",
            status="completed",
            extraction_result=repeated_extraction.model_dump(mode="json"),
        )
        session.add(repeated_document)
        await session.flush()
        repeated_invoice = await project_document(session, repeated_document)
        assert repeated_invoice is not None
        repeated_flag = await session.scalar(
            select(InvoiceRiskFlag).where(
                InvoiceRiskFlag.invoice_id == repeated_invoice.id,
                InvoiceRiskFlag.code == "repeated_invoice_number",
            )
        )
        assert repeated_flag is not None
        assert repeated_flag.points == 20
        assert repeated_invoice.status == InvoiceStatus.REVIEW_REQUIRED.value

    await engine.dispose()


async def test_two_way_and_three_way_po_matching():
    engine, session_factory = await _session()
    async with session_factory() as session:
        vendor = Vendor(
            tenant_id="local",
            name="ABC Technologies",
            normalized_name="abctechnologies",
            gstin="27ABCDE1234F1Z5",
        )
        session.add(vendor)
        await session.flush()
        purchase_order = PurchaseOrder(
            tenant_id="local",
            number="PO-1024",
            vendor_id=vendor.id,
            currency="INR",
            subtotal=Decimal("15000"),
            tax_total=Decimal("0"),
            total=Decimal("15000"),
        )
        session.add(purchase_order)
        await session.flush()
        po_item = PurchaseOrderItem(
            purchase_order_id=purchase_order.id,
            description="Keyboard",
            quantity=Decimal("10"),
            unit_price=Decimal("1500"),
            line_total=Decimal("15000"),
        )
        session.add(po_item)
        await session.flush()

        document = Document(
            tenant_id="local",
            filename="po-match.pdf",
            original_filename="po-match.pdf",
            file_path="po-match.pdf",
            status="completed",
            extraction_result=_po_extraction(
                invoice_number="INV-PO-1",
                po_number="PO-1024",
                quantity=Decimal("10"),
                grand_total=Decimal("15000"),
            ).model_dump(mode="json"),
        )
        session.add(document)
        await session.flush()
        invoice = await project_document(session, document)
        assert invoice is not None
        assert invoice.match_status == "matched"
        assert invoice.match_details["match_type"] == "two_way"
        assert invoice.match_details["match_message"] == "PO matched"

        receipt = GoodsReceipt(
            tenant_id="local",
            purchase_order_id=purchase_order.id,
            receipt_number="GR-1024",
            receipt_date=date(2026, 8, 5),
        )
        session.add(receipt)
        await session.flush()
        session.add(
            GoodsReceiptItem(
                goods_receipt_id=receipt.id,
                purchase_order_item_id=po_item.id,
                quantity_received=Decimal("10"),
            )
        )
        await session.flush()
        invoice = await project_document(session, document)
        assert invoice is not None
        assert invoice.match_status == "matched"
        assert invoice.match_details["three_way"] is True
        assert invoice.match_details["match_message"] == "Three-way match passed"

        mismatch_document = Document(
            tenant_id="local",
            filename="po-mismatch.pdf",
            original_filename="po-mismatch.pdf",
            file_path="po-mismatch.pdf",
            status="completed",
            extraction_result=_po_extraction(
                invoice_number="INV-PO-2",
                po_number="PO-1024",
                quantity=Decimal("14"),
                grand_total=Decimal("21000"),
            ).model_dump(mode="json"),
        )
        session.add(mismatch_document)
        await session.flush()
        mismatch_invoice = await project_document(session, mismatch_document)
        assert mismatch_invoice is not None
        assert mismatch_invoice.match_status == "mismatch"
        assert mismatch_invoice.match_details["match_type"] == "three_way"
        assert any(
            item["reason"] == "Invoice quantity exceeds received quantity"
            for item in mismatch_invoice.match_details["receipt_mismatches"]
        )
        assert mismatch_invoice.match_details["quantity_mismatches"][0]["invoice"] == "14"
        mismatch_risk_flags = list(
            await session.scalars(
                select(InvoiceRiskFlag).where(InvoiceRiskFlag.invoice_id == mismatch_invoice.id)
            )
        )
        po_risk = next(flag for flag in mismatch_risk_flags if flag.code == "po_mismatch")
        assert po_risk.points == 15
        assert po_risk.details["match_type"] == "three_way"

    await engine.dispose()


async def test_po_matching_reports_vendor_rate_and_tax_mismatches():
    engine, session_factory = await _session()
    async with session_factory() as session:
        po_vendor = Vendor(
            tenant_id="local",
            name="ABC Technologies",
            normalized_name="abctechnologies",
            gstin="27ABCDE1234F1Z5",
        )
        session.add(po_vendor)
        await session.flush()
        purchase_order = PurchaseOrder(
            tenant_id="local",
            number="PO-1025",
            vendor_id=po_vendor.id,
            currency="INR",
            subtotal=Decimal("15000"),
            tax_total=Decimal("2700"),
            total=Decimal("17700"),
        )
        session.add(purchase_order)
        await session.flush()
        session.add(
            PurchaseOrderItem(
                purchase_order_id=purchase_order.id,
                description="Keyboard",
                quantity=Decimal("10"),
                unit_price=Decimal("1500"),
                tax_rate=Decimal("18"),
                line_total=Decimal("15000"),
            )
        )
        await session.flush()

        extraction = _po_extraction(
            invoice_number="INV-PO-3",
            po_number="PO-1025",
            quantity=Decimal("10"),
            grand_total=Decimal("16000"),
        ).model_copy(
            update={
                "vendor": VendorDetails(
                    name=FieldValue(value="Other Supplier", confidence=0.96),
                    gstin=FieldValue(value="29ABCDE5678G1Z2", confidence=0.96),
                ),
                "line_items": [
                    LineItem(
                        description="Keyboard",
                        quantity=Decimal("10"),
                        unit_price=Decimal("1600"),
                        gst_rate=Decimal("5"),
                        line_total=Decimal("16000"),
                        confidence=0.95,
                    )
                ],
            }
        )
        document = Document(
            tenant_id="local",
            filename="po-controls-mismatch.pdf",
            original_filename="po-controls-mismatch.pdf",
            file_path="po-controls-mismatch.pdf",
            status="completed",
            extraction_result=extraction.model_dump(mode="json"),
        )
        session.add(document)
        await session.flush()
        invoice = await project_document(session, document)
        assert invoice is not None
        assert invoice.match_status == "mismatch"
        assert invoice.match_details["vendor_mismatches"]
        assert invoice.match_details["rate_mismatches"]
        assert invoice.match_details["tax_rate_mismatches"]
        assert invoice.match_details["tax_mismatches"]
        assert invoice.match_details["total_difference"] == "1700"

    await engine.dispose()


async def test_workflow_side_states_and_events_are_persisted():
    engine, session_factory = await _session()
    async with session_factory() as session:
        document = Document(
            tenant_id="local",
            filename="workflow-side-state.pdf",
            original_filename="workflow-side-state.pdf",
            file_path="workflow-side-state.pdf",
            status="completed",
            extraction_result=_extraction(number="INV-SIDE-1").model_dump(mode="json"),
        )
        session.add(document)
        await session.flush()
        invoice = await project_document(session, document)
        assert invoice is not None
        assert invoice.status == InvoiceStatus.REVIEW_REQUIRED.value

        await apply_workflow_action(session, invoice, WorkflowAction.HOLD, actor="reviewer")
        assert invoice.status == InvoiceStatus.ON_HOLD.value
        await apply_workflow_action(session, invoice, WorkflowAction.RELEASE, actor="reviewer")
        assert invoice.status == InvoiceStatus.REVIEW_REQUIRED.value
        await apply_workflow_action(session, invoice, WorkflowAction.REJECT, actor="reviewer")
        assert invoice.status == InvoiceStatus.REJECTED.value
        with pytest.raises(WorkflowError):
            await apply_workflow_action(session, invoice, WorkflowAction.HOLD)

        duplicate_document = Document(
            tenant_id="local",
            filename="workflow-duplicate.pdf",
            original_filename="workflow-duplicate.pdf",
            file_path="workflow-duplicate.pdf",
            status="completed",
            extraction_result=_extraction(number="INV-SIDE-2").model_dump(mode="json"),
        )
        session.add(duplicate_document)
        await session.flush()
        duplicate_invoice = await project_document(session, duplicate_document)
        assert duplicate_invoice is not None
        await apply_workflow_action(
            session, duplicate_invoice, WorkflowAction.MARK_DUPLICATE, actor="reviewer"
        )
        assert duplicate_invoice.status == InvoiceStatus.DUPLICATE.value

        events = list(
            await session.scalars(
                select(WorkflowEvent)
                .where(WorkflowEvent.invoice_id == invoice.id)
                .order_by(WorkflowEvent.created_at)
            )
        )
        assert [(event.from_status, event.to_status) for event in events] == [
            (None, InvoiceStatus.REVIEW_REQUIRED.value),
            (InvoiceStatus.REVIEW_REQUIRED.value, InvoiceStatus.ON_HOLD.value),
            (InvoiceStatus.ON_HOLD.value, InvoiceStatus.REVIEW_REQUIRED.value),
            (InvoiceStatus.REVIEW_REQUIRED.value, InvoiceStatus.REJECTED.value),
        ]
    await engine.dispose()


async def test_dashboard_summary_has_accounting_aging_buckets():
    engine, session_factory = await _session()
    async with session_factory() as session:
        today = date.today()
        due_dates = [
            today,
            today - timedelta(days=10),
            today - timedelta(days=45),
            today - timedelta(days=75),
            today - timedelta(days=120),
        ]
        for index, due_date in enumerate(due_dates, start=1):
            extraction = _extraction(number=f"INV-AGING-{index}").model_copy(
                update={"due_date": due_date.isoformat(), "grand_total": Decimal("100")}
            )
            document = Document(
                tenant_id="local",
                filename=f"aging-{index}.pdf",
                original_filename=f"aging-{index}.pdf",
                file_path=f"aging-{index}.pdf",
                status="completed",
                extraction_result=extraction.model_dump(mode="json"),
            )
            session.add(document)
            await session.flush()
            assert await project_document(session, document) is not None

        excluded_document = Document(
            tenant_id="local",
            filename="aging-duplicate.pdf",
            original_filename="aging-duplicate.pdf",
            file_path="aging-duplicate.pdf",
            status="completed",
            extraction_result=_extraction(number="INV-AGING-DUP").model_dump(mode="json"),
        )
        session.add(excluded_document)
        await session.flush()
        excluded_invoice = await project_document(session, excluded_document)
        assert excluded_invoice is not None
        excluded_invoice.status = InvoiceStatus.DUPLICATE.value

        summary = await dashboard_summary(session, "local")
        assert [bucket.label for bucket in summary.aging] == [
            "Current",
            "1–30 days",
            "31–60 days",
            "61–90 days",
            "90+ days",
        ]
        assert [bucket.amount for bucket in summary.aging] == [
            Decimal("100.00"),
            Decimal("100.00"),
            Decimal("100.00"),
            Decimal("100.00"),
            Decimal("100.00"),
        ]
        assert summary.total_invoices == 6
        assert summary.outstanding_total == Decimal("500.00")
        assert summary.overdue_total == Decimal("400.00")
    await engine.dispose()
