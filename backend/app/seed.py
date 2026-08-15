"""Create a repeatable fictional AP workspace for local demos.

Run with: ``python -m app.seed`` from the backend directory.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import async_session_factory, init_db
from app.domain.entities import (
    AIRun,
    AuditEntryModel,
    Document,
    DocumentEvent,
    DocumentJob,
    GoodsReceipt,
    GoodsReceiptItem,
    Invoice,
    InvoiceItem,
    InvoiceRiskFlag,
    InvoiceTax,
    InvoiceValidation,
    Payment,
    PurchaseOrder,
    PurchaseOrderItem,
    Vendor,
    WorkflowEvent,
)
from app.domain.schemas import (
    ExtractionSource,
    FieldValue,
    InvoiceExtraction,
    InvoiceStatus,
    LineItem,
    TaxDetails,
    TaxType,
    VendorDetails,
)
from app.services.ap_service import normalize_text, project_document, recalculate_outstanding


def _field(value: str | None, confidence: float = 0.96) -> FieldValue:
    return FieldValue(value=value, confidence=confidence, source=ExtractionSource.OCR_REGEX)


async def _reset_seed_workspace(session) -> None:
    documents = list(
        await session.scalars(
            select(Document).where(
                Document.tenant_id == "local", Document.document_hash.like("seed-ap-workspace%")
            )
        )
    )
    document_ids = [document.id for document in documents]
    invoices = (
        list(await session.scalars(select(Invoice).where(Invoice.document_id.in_(document_ids))))
        if document_ids
        else []
    )
    invoice_ids = [invoice.id for invoice in invoices]
    if invoice_ids:
        for model in (
            Payment,
            WorkflowEvent,
            InvoiceRiskFlag,
            InvoiceValidation,
            InvoiceTax,
            InvoiceItem,
        ):
            await session.execute(delete(model).where(model.invoice_id.in_(invoice_ids)))
        await session.execute(delete(AIRun).where(AIRun.invoice_id.in_(invoice_ids)))
        await session.execute(delete(Invoice).where(Invoice.id.in_(invoice_ids)))
    if document_ids:
        await session.execute(delete(AIRun).where(AIRun.document_id.in_(document_ids)))
        await session.execute(
            delete(AuditEntryModel).where(AuditEntryModel.document_id.in_(document_ids))
        )
        await session.execute(
            delete(DocumentEvent).where(DocumentEvent.document_id.in_(document_ids))
        )
        await session.execute(delete(DocumentJob).where(DocumentJob.document_id.in_(document_ids)))
        await session.execute(delete(Document).where(Document.id.in_(document_ids)))

    orders = list(
        await session.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.tenant_id == "local", PurchaseOrder.number == "PO-1024"
            )
        )
    )
    order_ids = [order.id for order in orders]
    if order_ids:
        receipt_ids = list(
            await session.scalars(
                select(GoodsReceipt.id).where(GoodsReceipt.purchase_order_id.in_(order_ids))
            )
        )
        if receipt_ids:
            await session.execute(
                delete(GoodsReceiptItem).where(GoodsReceiptItem.goods_receipt_id.in_(receipt_ids))
            )
            await session.execute(delete(GoodsReceipt).where(GoodsReceipt.id.in_(receipt_ids)))
        await session.execute(
            delete(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id.in_(order_ids))
        )
        await session.execute(delete(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids)))

    for vendor in list(
        await session.scalars(
            select(Vendor).where(
                Vendor.tenant_id == "local",
                Vendor.gstin.in_(["27ABCDE1234F1Z5", "29ABCDE5678G1Z2", "07ABCDE9012H1Z8"]),
            )
        )
    ):
        remaining = await session.scalar(select(Invoice.id).where(Invoice.vendor_id == vendor.id))
        if remaining is None:
            await session.delete(vendor)


async def seed(reset: bool = False) -> None:
    await init_db()
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(Document).where(
                Document.tenant_id == "local", Document.document_hash == "seed-ap-workspace"
            )
        )
        if existing:
            if not reset:
                print("Seed workspace already exists")
                return
            await _reset_seed_workspace(session)
            await session.commit()
            print("Reset the seeded AP workspace")

        today = date.today()
        vendors = [
            Vendor(
                tenant_id="local",
                name="ABC Technologies Pvt Ltd",
                normalized_name=normalize_text("ABC Technologies Pvt Ltd"),
                gstin="27ABCDE1234F1Z5",
                pan="ABCDE1234F",
                address="14 Maker Chambers, Mumbai, Maharashtra",
                payment_terms="30 days",
                bank_name="HDFC Bank",
                ifsc="HDFC0001234",
            ),
            Vendor(
                tenant_id="local",
                name="Zenix Office Systems",
                normalized_name=normalize_text("Zenix Office Systems"),
                gstin="29ABCDE5678G1Z2",
                pan="ABCDE5678G",
                address="22 Residency Road, Bengaluru, Karnataka",
                payment_terms="15 days",
            ),
            Vendor(
                tenant_id="local",
                name="Ravi Enterprises",
                normalized_name=normalize_text("Ravi Enterprises"),
                gstin="07ABCDE9012H1Z8",
                address="8 Nehru Place, New Delhi",
                payment_terms="45 days",
            ),
        ]
        session.add_all(vendors)
        await session.flush()

        po = PurchaseOrder(
            tenant_id="local",
            number="PO-1024",
            vendor_id=vendors[0].id,
            status="open",
            order_date=today - timedelta(days=12),
            expected_delivery=today + timedelta(days=9),
            currency="INR",
            subtotal=Decimal("102500"),
            tax_total=Decimal("18450"),
            total=Decimal("120950"),
            notes="Seed purchase order and receipt for three-way matching",
        )
        session.add(po)
        await session.flush()
        po_laptop = PurchaseOrderItem(
            purchase_order_id=po.id,
            description="Business laptop",
            quantity=2,
            unit_price=Decimal("50000"),
            tax_rate=18,
            line_total=Decimal("100000"),
        )
        po_mouse = PurchaseOrderItem(
            purchase_order_id=po.id,
            description="Wireless mouse",
            quantity=5,
            unit_price=Decimal("500"),
            tax_rate=18,
            line_total=Decimal("2500"),
        )
        session.add_all([po_laptop, po_mouse])
        await session.flush()
        receipt = GoodsReceipt(
            tenant_id="local",
            purchase_order_id=po.id,
            receipt_number="GR-1024",
            receipt_date=today - timedelta(days=7),
            notes="Seed receipt for three-way matching",
        )
        session.add(receipt)
        await session.flush()
        session.add_all(
            [
                GoodsReceiptItem(
                    goods_receipt_id=receipt.id,
                    purchase_order_item_id=po_laptop.id,
                    quantity_received=2,
                ),
                GoodsReceiptItem(
                    goods_receipt_id=receipt.id,
                    purchase_order_item_id=po_mouse.id,
                    quantity_received=5,
                ),
            ]
        )

        samples = [
            (
                "INV-2026-1024",
                "ABC Technologies Pvt Ltd",
                vendors[0].gstin,
                Decimal("120950"),
                date.today() - timedelta(days=4),
                today + timedelta(days=26),
                "PO-1024",
                InvoiceStatus.REVIEW_REQUIRED,
                [
                    LineItem(
                        description="Business laptop",
                        quantity=2,
                        unit_price=50000,
                        line_total=100000,
                        confidence=0.98,
                    ),
                    LineItem(
                        description="Wireless mouse",
                        quantity=5,
                        unit_price=500,
                        line_total=2500,
                        confidence=0.96,
                    ),
                ],
                [TaxDetails(tax_type=TaxType.CGST_SGST, rate_percent=18, amount=18450)],
            ),
            (
                "ZEN-8841",
                "Zenix Office Systems",
                vendors[1].gstin,
                Decimal("59000"),
                today - timedelta(days=18),
                today - timedelta(days=3),
                None,
                InvoiceStatus.AWAITING_PAYMENT,
                [
                    LineItem(
                        description="Office printers",
                        quantity=2,
                        unit_price=25000,
                        line_total=50000,
                        confidence=0.93,
                    )
                ],
                [TaxDetails(tax_type=TaxType.CGST_SGST, rate_percent=18, amount=9000)],
            ),
            (
                "RAVI-221",
                "Ravi Enterprises",
                vendors[2].gstin,
                Decimal("15800"),
                today - timedelta(days=2),
                today + timedelta(days=28),
                None,
                InvoiceStatus.REVIEW_REQUIRED,
                [
                    LineItem(
                        description="Network accessories",
                        quantity=4,
                        unit_price=3500,
                        line_total=14000,
                        confidence=0.69,
                    )
                ],
                [TaxDetails(tax_type=TaxType.IGST, rate_percent=12, amount=1800)],
            ),
            (
                "INV-2026-1024",
                "ABC Technologies Pvt Ltd",
                vendors[0].gstin,
                Decimal("120950"),
                today - timedelta(days=4),
                today + timedelta(days=27),
                "PO-1024",
                InvoiceStatus.DUPLICATE,
                [
                    LineItem(
                        description="Business laptop",
                        quantity=2,
                        unit_price=50000,
                        line_total=100000,
                        confidence=0.91,
                    )
                ],
                [TaxDetails(tax_type=TaxType.CGST_SGST, rate_percent=18, amount=18450)],
            ),
        ]
        invoices = []
        for index, (
            number,
            vendor_name,
            gstin,
            total,
            invoice_date,
            due_date,
            po_number,
            desired_status,
            items,
            taxes,
        ) in enumerate(samples, start=1):
            extraction = InvoiceExtraction(
                invoice_number=_field(number),
                invoice_date=invoice_date.isoformat(),
                due_date=due_date.isoformat(),
                po_reference=_field(po_number) if po_number else None,
                payment_terms="30 days",
                vendor=VendorDetails(
                    name=_field(vendor_name),
                    gstin=_field(gstin),
                    address=_field("Fictional supplier address"),
                ),
                line_items=items,
                taxes=taxes,
                subtotal=total - sum(tax.amount for tax in taxes),
                tax_total=sum(tax.amount for tax in taxes),
                grand_total=total,
                currency="INR",
                overall_confidence=0.96 if index != 3 else 0.72,
                extraction_source=ExtractionSource.OCR_REGEX,
            )
            document = Document(
                tenant_id="local",
                filename=f"seed-{number}.pdf",
                original_filename=f"seed-{number}.pdf",
                file_path="",
                file_size_bytes=0,
                mime_type="application/pdf",
                page_count=1,
                status="completed",
                extraction_result=extraction.model_dump(mode="json"),
                overall_confidence=extraction.overall_confidence,
                processing_time_ms=420 + index * 80,
                extraction_source=extraction.extraction_source.value,
                vendor_name=vendor_name,
                grand_total=float(total),
                currency="INR",
                document_hash="seed-ap-workspace" if index == 1 else f"seed-ap-workspace-{index}",
            )
            session.add(document)
            await session.flush()
            invoice = await project_document(session, document)
            if invoice:
                invoices.append((invoice, desired_status))

        await session.flush()
        for invoice, desired_status in invoices:
            if desired_status == InvoiceStatus.AWAITING_PAYMENT:
                invoice.status = InvoiceStatus.AWAITING_PAYMENT.value
                session.add(
                    Payment(
                        invoice_id=invoice.id,
                        tenant_id="local",
                        amount=Decimal("10000"),
                        payment_date=today - timedelta(days=2),
                        method="bank_transfer",
                        reference="UTR-SEED-8841",
                    )
                )
            elif desired_status == InvoiceStatus.DUPLICATE:
                invoice.status = InvoiceStatus.DUPLICATE.value
            await recalculate_outstanding(session, invoice)
        await session.commit()
        print(f"Seeded {len(invoices)} invoices, {len(vendors)} vendors, and PO-1024")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed or reset the fictional AP workspace")
    parser.add_argument("--reset", action="store_true", help="Remove existing seeded records first")
    asyncio.run(seed(reset=parser.parse_args().reset))
