"""Accounts-payable projection, workflow, matching, and analytics services.

The document pipeline remains the source of extraction evidence.  This module
projects that evidence into normalized AP records and owns the business state
machine used by the dashboard.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal

from dateutil import parser as date_parser
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.entities import (
    AuditEntryModel,
    Document,
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
    AgingBucket,
    APDashboardSummary,
    DocumentStatus,
    InvoiceExtraction,
    InvoiceStatus,
    MatchStatus,
    RiskLevel,
    ValidationFlag,
    ValidationSeverity,
    WorkflowAction,
)
from app.extraction.gst import normalize_gstin
from app.extraction.pan import normalize_pan
from app.services.validation_service import ValidationService
from app.utils.text import normalize_text
from app.validation.duplicate_validator import (
    duplicate_fingerprint,
    duplicate_fingerprint_components,
)

logger = get_logger(__name__)

PO_MATCH_TOLERANCE = Decimal("1.00")
PO_QUANTITY_TOLERANCE = Decimal("0.0001")
AMOUNT_ANOMALY_MULTIPLIER = Decimal("3")
AMOUNT_ANOMALY_MIN_DIFFERENCE = Decimal("1000")
LARGE_PURCHASE_THRESHOLD = Decimal("1000000")


def parse_date(value: str | date | datetime | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text_value = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text_value):
        try:
            return date.fromisoformat(text_value)
        except ValueError:
            return None
    try:
        return date_parser.parse(text_value, dayfirst=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


def decimal_value(
    value: Decimal | float | int | str | None, default: Decimal = Decimal("0")
) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _level_for_points(points: int) -> RiskLevel:
    if points >= 25:
        return RiskLevel.HIGH
    if points >= 15:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _flag_key(flag: ValidationFlag) -> tuple[str, str]:
    return flag.rule, flag.message


async def _upsert_vendor(
    session: AsyncSession,
    extraction: InvoiceExtraction,
    tenant_id: str,
) -> tuple[Vendor, bool, dict[str, dict]]:
    vendor_name = extraction.vendor.name.value or "Unknown vendor"
    normalized_name = normalize_text(vendor_name)
    gstin = (
        normalize_gstin(extraction.vendor.gstin.value)
        if extraction.vendor.gstin and extraction.vendor.gstin.value
        else None
    )

    vendor = None
    if gstin:
        vendor = await session.scalar(
            select(Vendor).where(Vendor.tenant_id == tenant_id, Vendor.gstin == gstin).limit(1)
        )
    if vendor is None and normalized_name:
        vendor = await session.scalar(
            select(Vendor)
            .where(Vendor.tenant_id == tenant_id, Vendor.normalized_name == normalized_name)
            .limit(1)
        )

    is_new = vendor is None
    risk_signals: dict[str, dict] = {}
    if vendor is None:
        vendor = Vendor(
            tenant_id=tenant_id,
            name=vendor_name,
            normalized_name=normalized_name or "unknownvendor",
        )
        session.add(vendor)
        await session.flush()

    if (
        not is_new
        and gstin
        and vendor.gstin
        and normalize_gstin(vendor.gstin) != gstin
    ):
        risk_signals["gstin_mismatch"] = {
            "vendor_master": vendor.gstin,
            "invoice": gstin,
        }

    vendor.name = vendor_name
    vendor.normalized_name = normalized_name or vendor.normalized_name
    if gstin and not risk_signals.get("gstin_mismatch"):
        vendor.gstin = gstin
    vendor.pan = (
        normalize_pan(extraction.vendor.pan.value)
        if extraction.vendor.pan and extraction.vendor.pan.value
        else vendor.pan
    )
    vendor.address = (
        extraction.vendor.address.value
        if extraction.vendor.address and extraction.vendor.address.value
        else vendor.address
    )
    incoming_bank_account = (
        extraction.vendor.bank_account.value
        if extraction.vendor.bank_account and extraction.vendor.bank_account.value
        else None
    )
    incoming_bank_name = (
        extraction.vendor.bank_name.value
        if extraction.vendor.bank_name and extraction.vendor.bank_name.value
        else None
    )
    incoming_ifsc = (
        extraction.vendor.ifsc.value
        if extraction.vendor.ifsc and extraction.vendor.ifsc.value
        else None
    )
    bank_changes: dict[str, dict[str, str | None]] = {}
    for field_name, incoming in (
        ("bank_account", incoming_bank_account),
        ("bank_name", incoming_bank_name),
        ("ifsc", incoming_ifsc),
    ):
        existing = getattr(vendor, field_name)
        if incoming and existing and normalize_text(existing) != normalize_text(incoming):
            bank_changes[field_name] = {"vendor_master": existing, "invoice": incoming}
        elif incoming:
            setattr(vendor, field_name, incoming)
    if bank_changes:
        risk_signals["bank_details_changed"] = bank_changes
    vendor.email = (
        extraction.vendor.email.value
        if extraction.vendor.email and extraction.vendor.email.value
        else vendor.email
    )
    vendor.phone = (
        extraction.vendor.phone.value
        if extraction.vendor.phone and extraction.vendor.phone.value
        else vendor.phone
    )
    vendor.payment_terms = extraction.payment_terms or vendor.payment_terms
    return vendor, is_new, risk_signals


async def _find_po_match(
    session: AsyncSession,
    invoice: Invoice,
    extraction: InvoiceExtraction,
) -> tuple[MatchStatus, dict]:
    if not invoice.po_number:
        return MatchStatus.NOT_APPLICABLE, {"reason": "No PO reference extracted"}

    purchase_order = await session.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == invoice.tenant_id,
            func.lower(PurchaseOrder.number) == invoice.po_number.casefold(),
        )
    )
    if purchase_order is None:
        return MatchStatus.MISMATCH, {
            "reason": f"PO {invoice.po_number} was not found",
            "match_type": "two_way",
        }

    po_items = list(
        await session.scalars(
            select(PurchaseOrderItem).where(
                PurchaseOrderItem.purchase_order_id == purchase_order.id
            )
        )
    )
    quantity_mismatches: list[dict] = []
    rate_mismatches: list[dict] = []
    tax_rate_mismatches: list[dict] = []
    quantity_variances: list[dict] = []
    matched_po_item_ids: set[str] = set()
    for invoice_item in extraction.line_items:
        needle = normalize_text(invoice_item.description)
        candidate = next(
            (
                item
                for item in po_items
                if item.id not in matched_po_item_ids
                and normalize_text(item.description) == needle
            ),
            None,
        )
        if candidate is None:
            quantity_mismatches.append(
                {"description": invoice_item.description, "reason": "Not on PO"}
            )
            continue
        matched_po_item_ids.add(candidate.id)
        if invoice_item.quantity < candidate.quantity:
            quantity_variances.append(
                {
                    "description": invoice_item.description,
                    "invoice": str(invoice_item.quantity),
                    "po": str(candidate.quantity),
                    "kind": "partial_invoice",
                }
            )
        if invoice_item.quantity > candidate.quantity:
            quantity_mismatches.append(
                {
                    "description": invoice_item.description,
                    "invoice": str(invoice_item.quantity),
                    "po": str(candidate.quantity),
                }
            )
        if abs(invoice_item.unit_price - candidate.unit_price) > Decimal("0.01"):
            rate_mismatches.append(
                {
                    "description": invoice_item.description,
                    "invoice": str(invoice_item.unit_price),
                    "po": str(candidate.unit_price),
                }
            )
        if (
            invoice_item.gst_rate is not None
            and candidate.tax_rate is not None
            and abs(invoice_item.gst_rate - candidate.tax_rate) > Decimal("0.01")
        ):
            tax_rate_mismatches.append(
                {
                    "description": invoice_item.description,
                    "invoice": str(invoice_item.gst_rate),
                    "po": str(candidate.tax_rate),
                }
            )

    unbilled_po_items = [
        {
            "description": item.description,
            "po": str(item.quantity),
        }
        for item in po_items
        if item.id not in matched_po_item_ids
    ]

    vendor_mismatches: list[dict] = []
    vendor_match: bool | None = None
    if purchase_order.vendor_id:
        vendor_match = invoice.vendor_id == purchase_order.vendor_id
        if not vendor_match:
            vendor_mismatches.append(
                {
                    "invoice_vendor_id": invoice.vendor_id,
                    "po_vendor_id": purchase_order.vendor_id,
                }
            )

    invoice_total = decimal_value(invoice.grand_total)
    po_total = decimal_value(purchase_order.total)
    total_difference = abs(invoice_total - po_total)
    total_tolerance = PO_MATCH_TOLERANCE
    invoice_tax = decimal_value(extraction.tax_total)
    po_tax = decimal_value(purchase_order.tax_total)
    tax_difference = abs(invoice_tax - po_tax)
    tax_mismatches: list[dict] = []
    if tax_difference > PO_MATCH_TOLERANCE:
        tax_mismatches.append(
            {
                "invoice": str(invoice_tax),
                "po": str(po_tax),
                "difference": str(tax_difference),
            }
        )

    currency_mismatches: list[dict] = []
    if (extraction.currency or "INR").upper() != (purchase_order.currency or "INR").upper():
        currency_mismatches.append(
            {
                "invoice": extraction.currency,
                "po": purchase_order.currency,
            }
        )

    receipt_items = list(
        await session.scalars(
            select(GoodsReceiptItem)
            .join(GoodsReceipt, GoodsReceiptItem.goods_receipt_id == GoodsReceipt.id)
            .where(GoodsReceipt.purchase_order_id == purchase_order.id)
        )
    )
    received_by_po_item: dict[str, Decimal] = {}
    for receipt_item in receipt_items:
        received_by_po_item[receipt_item.purchase_order_item_id] = (
            received_by_po_item.get(receipt_item.purchase_order_item_id, Decimal("0"))
            + receipt_item.quantity_received
    )
    receipt_mismatches: list[dict] = []
    if receipt_items:
        for po_item in po_items:
            received = received_by_po_item.get(po_item.id, Decimal("0"))
            if received > po_item.quantity + PO_QUANTITY_TOLERANCE:
                receipt_mismatches.append(
                    {
                        "description": po_item.description,
                        "po": str(po_item.quantity),
                        "received": str(received),
                        "reason": "Received quantity exceeds PO quantity",
                    }
                )
        for invoice_item in extraction.line_items:
            needle = normalize_text(invoice_item.description)
            candidate = next(
                (item for item in po_items if normalize_text(item.description) == needle),
                None,
            )
            if candidate:
                received = received_by_po_item.get(candidate.id, Decimal("0"))
                if invoice_item.quantity > received + PO_QUANTITY_TOLERANCE:
                    receipt_mismatches.append(
                        {
                            "description": invoice_item.description,
                            "po": str(candidate.quantity),
                            "invoice": str(invoice_item.quantity),
                            "received": str(received),
                            "reason": "Invoice quantity exceeds received quantity",
                        }
                    )

    match_type = "three_way" if receipt_items else "two_way"
    hard_reasons: list[str] = []
    if vendor_mismatches:
        hard_reasons.append("Vendor mismatch")
    if quantity_mismatches:
        hard_reasons.append("PO quantity mismatch")
    if rate_mismatches:
        hard_reasons.append("PO rate mismatch")
    if tax_rate_mismatches or tax_mismatches:
        hard_reasons.append("PO tax mismatch")
    if receipt_mismatches:
        hard_reasons.append("Three-way quantity mismatch")
    if currency_mismatches:
        hard_reasons.append("Currency mismatch")
    if total_difference > total_tolerance and invoice_total > po_total:
        hard_reasons.append("PO total mismatch")

    details = {
        "po_id": purchase_order.id,
        "po_number": purchase_order.number,
        "match_type": match_type,
        "vendor_match": vendor_match,
        "invoice_total": str(invoice_total),
        "po_total": str(po_total),
        "total_difference": str(total_difference),
        "total_tolerance": str(total_tolerance),
        "invoice_tax": str(invoice_tax),
        "po_tax": str(po_tax),
        "tax_difference": str(tax_difference),
        "quantity_mismatches": quantity_mismatches,
        "quantity_variances": quantity_variances,
        "unbilled_po_items": unbilled_po_items,
        "rate_mismatches": rate_mismatches,
        "tax_rate_mismatches": tax_rate_mismatches,
        "tax_mismatches": tax_mismatches,
        "vendor_mismatches": vendor_mismatches,
        "currency_mismatches": currency_mismatches,
        "receipt_mismatches": receipt_mismatches,
        "three_way": bool(receipt_items),
    }
    if hard_reasons:
        details["reason"] = "; ".join(hard_reasons)
        return MatchStatus.MISMATCH, details
    if total_difference > total_tolerance or unbilled_po_items or quantity_variances:
        details["reason"] = "Partial PO match"
        details["match_message"] = (
            "Three-way match partially passed" if receipt_items else "PO partially matched"
        )
        return MatchStatus.PARTIAL, details
    details["reason"] = "Three-way match passed" if receipt_items else "PO matched"
    details["match_message"] = details["reason"]
    return MatchStatus.MATCHED, details


def _risk_inputs(
    extraction: InvoiceExtraction,
    validation_flags: Iterable[ValidationFlag],
    *,
    new_vendor: bool,
    duplicate: bool,
    match_status: MatchStatus,
    vendor_risk_signals: dict[str, dict] | None = None,
    duplicate_details: dict | None = None,
    match_details: dict | None = None,
    amount_anomaly_details: dict | None = None,
) -> list[tuple[str, int, str, dict]]:
    flags: list[tuple[str, int, str, dict]] = []
    vendor_risk_signals = vendor_risk_signals or {}
    if duplicate:
        flags.append(
            (
                "duplicate_invoice",
                40,
                "Possible duplicate invoice detected",
                duplicate_details or {},
            )
        )
    if new_vendor:
        flags.append(
            (
                "unknown_vendor",
                15,
                "Vendor was not in the vendor master; a new vendor record was created",
                {
                    "vendor_name": extraction.vendor.name.value,
                    "gstin": extraction.vendor.gstin.value
                    if extraction.vendor.gstin
                    else None,
                },
            )
        )
    if vendor_risk_signals.get("gstin_mismatch"):
        flags.append(
            (
                "gstin_mismatch",
                20,
                "Invoice GSTIN differs from the vendor master",
                vendor_risk_signals["gstin_mismatch"],
            )
        )
    if vendor_risk_signals.get("bank_details_changed"):
        flags.append(
            (
                "bank_details_changed",
                25,
                "Invoice bank details differ from the vendor master",
                vendor_risk_signals["bank_details_changed"],
            )
        )
    if match_status in {MatchStatus.MISMATCH, MatchStatus.PARTIAL}:
        flags.append(
            (
                "po_mismatch",
                15,
                f"Purchase-order match is {match_status.value}",
                match_details or {},
            )
        )

    for validation in validation_flags:
        if validation.passed:
            continue
        # These checks have a dedicated risk contribution above. Keeping the
        # validation record for the UI but scoring it once makes the score
        # auditable and prevents accidental double counting.
        if validation.rule in {"duplicate_invoice", "purchase_order"}:
            continue
        points = {
            "required_fields": 25,
            "arithmetic": 10,
            "tax_total": 10,
            "tax_consistency": 10,
            "gstin": 10,
            "pan": 10,
            "date_order": 5,
            "date_parseable": 5,
            "due_date_parseable": 5,
            "date_future": 5,
            "repeated_invoice_number": 20,
            "qr_ocr_mismatch": 15,
        }.get(validation.rule, 5)
        flags.append((validation.rule, points, validation.message, validation.details))

    if amount_anomaly_details:
        flags.append(
            (
                "amount_anomaly",
                10,
                "Invoice total is unusually high compared with this vendor's history",
                amount_anomaly_details,
            )
        )
    if extraction.grand_total is not None and extraction.grand_total >= LARGE_PURCHASE_THRESHOLD:
        flags.append(
            (
                "large_purchase",
                10,
                "Invoice total is unusually large (above ₹10,00,000)",
                {
                    "amount": str(extraction.grand_total),
                    "threshold": str(LARGE_PURCHASE_THRESHOLD),
                },
            )
        )
    return flags


async def _find_duplicate_invoice(
    session: AsyncSession,
    *,
    tenant_id: str,
    vendor_id: str | None,
    normalized_invoice_number: str | None,
    fingerprint: str | None,
    current_invoice: Invoice | None,
) -> tuple[Invoice | None, str | None]:
    """Find the first earlier tenant-scoped match and explain the match type."""

    base_filters = [
        Invoice.tenant_id == tenant_id,
        Invoice.status != InvoiceStatus.REJECTED.value,
    ]
    if current_invoice is not None:
        base_filters.append(Invoice.id != current_invoice.id)
        if current_invoice.created_at is not None:
            base_filters.append(
                or_(
                    Invoice.created_at < current_invoice.created_at,
                    and_(
                        Invoice.created_at == current_invoice.created_at,
                        Invoice.id < current_invoice.id,
                    ),
                )
            )

    if fingerprint:
        fingerprint_match = await session.scalar(
            select(Invoice)
            .where(*base_filters, Invoice.duplicate_fingerprint == fingerprint)
            .order_by(Invoice.created_at, Invoice.id)
            .limit(1)
        )
        if fingerprint_match is not None:
            return fingerprint_match, "sha256_fingerprint"

    if not vendor_id or not normalized_invoice_number:
        return None, None
    legacy_filters = [
        *base_filters,
        Invoice.vendor_id == vendor_id,
        Invoice.normalized_invoice_number == normalized_invoice_number,
    ]
    # Once a complete fingerprint is available, only use this fallback for
    # pre-fingerprint rows created before the migration.
    if fingerprint:
        legacy_filters.append(Invoice.duplicate_fingerprint.is_(None))
    legacy_match = await session.scalar(
        select(Invoice)
        .where(*legacy_filters)
        .order_by(Invoice.created_at, Invoice.id)
        .limit(1)
    )
    return (legacy_match, "legacy_business_key") if legacy_match is not None else (None, None)


async def _find_repeated_invoice_number(
    session: AsyncSession,
    *,
    tenant_id: str,
    vendor_id: str | None,
    normalized_invoice_number: str | None,
    current_invoice: Invoice | None,
) -> Invoice | None:
    """Find a prior invoice reusing the vendor's invoice number.

    This intentionally differs from exact duplicate detection: a repeated
    number with a different date or amount is still suspicious, but should not
    be silently classified as the same document.
    """

    if not vendor_id or not normalized_invoice_number:
        return None
    filters = [
        Invoice.tenant_id == tenant_id,
        Invoice.vendor_id == vendor_id,
        Invoice.normalized_invoice_number == normalized_invoice_number,
        Invoice.status != InvoiceStatus.REJECTED.value,
    ]
    if current_invoice is not None:
        filters.append(Invoice.id != current_invoice.id)
    return await session.scalar(
        select(Invoice)
        .where(*filters)
        .order_by(Invoice.created_at, Invoice.id)
        .limit(1)
    )


async def _find_amount_anomaly(
    session: AsyncSession,
    *,
    invoice: Invoice,
    amount: Decimal | None,
) -> dict | None:
    """Compare a new total with the vendor's non-side-state history."""

    if invoice.vendor_id is None or amount is None or amount <= 0:
        return None
    historical_values = list(
        await session.scalars(
            select(Invoice.grand_total).where(
                Invoice.tenant_id == invoice.tenant_id,
                Invoice.vendor_id == invoice.vendor_id,
                Invoice.id != invoice.id,
                Invoice.grand_total.is_not(None),
                Invoice.status.notin_(
                    [
                        InvoiceStatus.REJECTED.value,
                        InvoiceStatus.DUPLICATE.value,
                    ]
                ),
            )
        )
    )
    history = [decimal_value(value) for value in historical_values if decimal_value(value) > 0]
    if not history:
        return None
    average = sum(history, Decimal("0")) / len(history)
    if (
        amount < average * AMOUNT_ANOMALY_MULTIPLIER
        or amount - average < AMOUNT_ANOMALY_MIN_DIFFERENCE
    ):
        return None
    return {
        "amount": str(amount),
        "historical_average": f"{average:.2f}",
        "multiplier": str(AMOUNT_ANOMALY_MULTIPLIER),
        "minimum_difference": str(AMOUNT_ANOMALY_MIN_DIFFERENCE),
        "previous_invoice_count": len(history),
    }


async def project_document(
    session: AsyncSession,
    document: Document,
) -> Invoice | None:
    """Upsert the normalized AP record for a completed document."""

    if not document.extraction_result:
        return None
    extraction = InvoiceExtraction.model_validate(document.extraction_result)
    # Backfill the universal nested contract for legacy or freshly corrected
    # extraction payloads before projecting to the relational AP aggregate.
    extraction.ensure_standardized()
    tenant_id = document.tenant_id
    vendor, new_vendor, vendor_risk_signals = await _upsert_vendor(
        session, extraction, tenant_id
    )
    fingerprint = duplicate_fingerprint(extraction)
    fingerprint_components = duplicate_fingerprint_components(extraction)
    invoice = await session.scalar(
        select(Invoice).where(Invoice.document_id == document.id, Invoice.tenant_id == tenant_id)
    )
    is_new_invoice = invoice is None
    existing_status = invoice.status if invoice is not None else None
    duplicate_query, duplicate_match_type = await _find_duplicate_invoice(
        session,
        tenant_id=tenant_id,
        vendor_id=vendor.id,
        normalized_invoice_number=normalize_text(extraction.invoice_number.value),
        fingerprint=fingerprint,
        current_invoice=invoice,
    )
    if invoice is None:
        invoice = Invoice(document_id=document.id, tenant_id=tenant_id)
        session.add(invoice)
        await session.flush()

    invoice.vendor_id = vendor.id
    invoice.invoice_number = extraction.invoice_number.value
    invoice.normalized_invoice_number = normalize_text(extraction.invoice_number.value)
    invoice.duplicate_fingerprint = fingerprint
    invoice.invoice_date = parse_date(extraction.invoice_date)
    invoice.due_date = parse_date(extraction.due_date)
    invoice.po_number = extraction.po_reference.value if extraction.po_reference else None
    invoice.currency = extraction.currency or "INR"
    invoice.subtotal = extraction.subtotal
    invoice.discount_total = extraction.discount_total
    invoice.taxable_amount = (
        (extraction.subtotal or Decimal("0")) - extraction.discount_total
        if extraction.subtotal is not None
        else None
    )
    invoice.tax_total = extraction.tax_total
    invoice.grand_total = extraction.grand_total
    invoice.overall_confidence = extraction.overall_confidence
    invoice.confidence_score = extraction.overall_confidence
    invoice.ocr_text = document.ocr_text

    # Keep the common GST columns queryable while retaining the normalized
    # invoice_taxes rows as the source of truth for arbitrary tax types.
    invoice.cgst = Decimal("0.00")
    invoice.sgst = Decimal("0.00")
    invoice.igst = Decimal("0.00")
    for tax in extraction.taxes:
        tax_type = tax.tax_type.value if hasattr(tax.tax_type, "value") else str(tax.tax_type)
        if tax_type == "CGST":
            invoice.cgst += tax.amount
        elif tax_type == "SGST":
            invoice.sgst += tax.amount
        elif tax_type == "IGST":
            invoice.igst += tax.amount
        elif tax_type == "CGST_SGST":
            half = tax.amount / 2
            invoice.cgst += half
            invoice.sgst += tax.amount - half

    repeated_invoice = await _find_repeated_invoice_number(
        session,
        tenant_id=tenant_id,
        vendor_id=vendor.id,
        normalized_invoice_number=invoice.normalized_invoice_number,
        current_invoice=invoice,
    )
    amount_anomaly_details = await _find_amount_anomaly(
        session,
        invoice=invoice,
        amount=invoice.grand_total,
    )

    await session.execute(delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
    await session.execute(delete(InvoiceTax).where(InvoiceTax.invoice_id == invoice.id))
    await session.execute(
        delete(InvoiceValidation).where(InvoiceValidation.invoice_id == invoice.id)
    )
    await session.execute(delete(InvoiceRiskFlag).where(InvoiceRiskFlag.invoice_id == invoice.id))

    for item in extraction.line_items:
        taxable_value = max(Decimal("0"), item.quantity * item.unit_price - item.discount)
        session.add(
            InvoiceItem(
                invoice_id=invoice.id,
                description=item.description,
                hsn=item.hsn_sac,
                hsn_sac=item.hsn_sac,
                quantity=item.quantity,
                unit_price=item.unit_price,
                rate=item.unit_price,
                discount=item.discount,
                taxable_value=taxable_value,
                gst_rate=item.gst_rate,
                tax_amount=item.tax_amount,
                tax=item.tax_amount,
                line_total=item.line_total,
                confidence=item.confidence,
            )
        )
    for tax in extraction.taxes:
        session.add(
            InvoiceTax(
                invoice_id=invoice.id,
                tax_type=tax.tax_type.value,
                rate_percent=tax.rate_percent,
                amount=tax.amount,
            )
        )

    validation_flags = ValidationService().validate(extraction)
    for existing in extraction.validation_flags:
        if _flag_key(existing) not in {_flag_key(flag) for flag in validation_flags}:
            validation_flags.append(existing)

    def add_validation(flag: ValidationFlag) -> None:
        if _flag_key(flag) not in {_flag_key(existing) for existing in validation_flags}:
            validation_flags.append(flag)

    duplicate = duplicate_query is not None
    duplicate_details: dict = {}
    if duplicate_query is not None:
        previous_date = (
            duplicate_query.invoice_date.isoformat()
            if duplicate_query.invoice_date
            else "not available"
        )
        previous_amount = decimal_value(duplicate_query.grand_total)
        previous_amount_text = f"{previous_amount:.2f}"
        currency_prefix = "₹" if invoice.currency.upper() == "INR" else f"{invoice.currency} "
        duplicate_details = {
            "duplicate_of": duplicate_query.id,
            "previously_uploaded": previous_date,
            "supplier": vendor.name,
            "amount": previous_amount_text,
            "fingerprint": fingerprint,
            "fingerprint_components": fingerprint_components or {},
            "match_type": duplicate_match_type or "unknown",
        }
        add_validation(
            ValidationFlag(
                rule="duplicate_invoice",
                passed=False,
                message=(
                    "Possible Duplicate Invoice. "
                    f"Previously uploaded: {previous_date}. "
                    f"Supplier: {vendor.name}. "
                    f"Amount: {currency_prefix}{previous_amount:,.2f}."
                ),
                severity=ValidationSeverity.ERROR,
                details=duplicate_details,
            )
        )
    if repeated_invoice is not None and not duplicate:
        repeated_details = {
            "previous_invoice_id": repeated_invoice.id,
            "previous_invoice_date": (
                repeated_invoice.invoice_date.isoformat()
                if repeated_invoice.invoice_date
                else None
            ),
            "previous_amount": str(decimal_value(repeated_invoice.grand_total)),
            "invoice_number": invoice.invoice_number,
        }
        add_validation(
            ValidationFlag(
                rule="repeated_invoice_number",
                passed=False,
                message=(
                    "Invoice number was previously used for this vendor; "
                    "review whether this is a legitimate reissue"
                ),
                severity=ValidationSeverity.WARNING,
                details=repeated_details,
            )
        )

    match_status, match_details = await _find_po_match(session, invoice, extraction)
    invoice.match_status = match_status.value
    invoice.match_details = match_details
    if match_status == MatchStatus.MISMATCH:
        add_validation(
            ValidationFlag(
                rule="purchase_order",
                passed=False,
                message=match_details.get("reason", "Purchase-order mismatch"),
                severity=ValidationSeverity.WARNING,
            )
        )
    for flag in validation_flags:
        session.add(
            InvoiceValidation(
                invoice_id=invoice.id,
                rule=flag.rule,
                passed=flag.passed,
                severity=flag.severity.value,
                message=flag.message,
                details=(
                    match_details
                    if flag.rule == "purchase_order"
                    else flag.details
                ),
            )
        )

    risk_inputs = _risk_inputs(
        extraction,
        validation_flags,
        new_vendor=new_vendor,
        duplicate=duplicate,
        match_status=match_status,
        vendor_risk_signals=vendor_risk_signals,
        duplicate_details=duplicate_details if duplicate else None,
        match_details=match_details,
        amount_anomaly_details=amount_anomaly_details,
    )
    risk_score = min(100, sum(points for _, points, _, _ in risk_inputs))
    invoice.risk_score = risk_score
    invoice.risk_level = (
        RiskLevel.HIGH.value
        if risk_score >= 50
        else RiskLevel.MEDIUM.value
        if risk_score >= 20
        else RiskLevel.LOW.value
    )
    for code, points, message, details in risk_inputs:
        session.add(
            InvoiceRiskFlag(
                invoice_id=invoice.id,
                code=code,
                points=points,
                level=_level_for_points(points).value,
                message=message,
                details=details,
            )
        )

    blocking = [
        flag
        for flag in validation_flags
        if not flag.passed and flag.severity == ValidationSeverity.ERROR
    ]
    if duplicate and existing_status not in {
        InvoiceStatus.PAID.value,
        InvoiceStatus.REJECTED.value,
    }:
        invoice.status = InvoiceStatus.DUPLICATE.value
        invoice.review_reason = "Duplicate invoice detected"
    elif existing_status in {
        None,
        InvoiceStatus.REVIEW_REQUIRED.value,
        InvoiceStatus.DUPLICATE.value,
    }:
        invoice.status = InvoiceStatus.REVIEW_REQUIRED.value
        invoice.review_reason = "; ".join(flag.message for flag in blocking[:3]) or None
    if is_new_invoice:
        session.add(
            WorkflowEvent(
                invoice_id=invoice.id,
                tenant_id=invoice.tenant_id,
                action="projection_completed",
                from_status=None,
                to_status=invoice.status,
                actor="system",
                comment="Extraction projected into the AP workflow",
            )
        )
    extraction.validation_flags = validation_flags
    document.extraction_result = extraction.model_dump(mode="json")
    await recalculate_outstanding(session, invoice)
    document.status = DocumentStatus.COMPLETED.value
    await session.flush()
    return invoice


async def recalculate_outstanding(session: AsyncSession, invoice: Invoice) -> Decimal:
    paid = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.invoice_id == invoice.id,
            Payment.tenant_id == invoice.tenant_id,
            Payment.status == "confirmed",
        )
    )
    total = decimal_value(invoice.grand_total)
    invoice.outstanding_amount = max(Decimal("0"), total - decimal_value(paid))
    if invoice.outstanding_amount <= Decimal("0") and total > Decimal("0"):
        invoice.status = InvoiceStatus.PAID.value
    return invoice.outstanding_amount


class WorkflowError(ValueError):
    """Raised when an AP transition is not allowed."""


async def apply_workflow_action(
    session: AsyncSession,
    invoice: Invoice,
    action: WorkflowAction,
    *,
    actor: str = "local_user",
    comment: str | None = None,
    override: bool = False,
) -> Invoice:
    current = InvoiceStatus(invoice.status)
    target: InvoiceStatus
    if action == WorkflowAction.APPROVE:
        if current not in {
            InvoiceStatus.REVIEW_REQUIRED,
            InvoiceStatus.ON_HOLD,
            InvoiceStatus.DUPLICATE,
        }:
            raise WorkflowError(f"Cannot approve an invoice in {current.value} state")
        blocking = list(
            await session.scalars(
                select(InvoiceValidation).where(
                    InvoiceValidation.invoice_id == invoice.id,
                    InvoiceValidation.passed.is_(False),
                    InvoiceValidation.severity == ValidationSeverity.ERROR.value,
                )
            )
        )
        if (
            blocking
            or invoice.risk_level == RiskLevel.HIGH.value
            or invoice.match_status == MatchStatus.MISMATCH.value
        ) and not override:
            raise WorkflowError(
                "Approval requires an override because blocking risk or validation flags remain"
            )
        target = InvoiceStatus.APPROVED
    elif action == WorkflowAction.REJECT:
        if current in {InvoiceStatus.PAID, InvoiceStatus.REJECTED}:
            raise WorkflowError(f"Cannot reject an invoice in {current.value} state")
        target = InvoiceStatus.REJECTED
    elif action == WorkflowAction.HOLD:
        if current in {InvoiceStatus.PAID, InvoiceStatus.REJECTED}:
            raise WorkflowError(f"Cannot hold an invoice in {current.value} state")
        target = InvoiceStatus.ON_HOLD
    elif action == WorkflowAction.RELEASE:
        if current != InvoiceStatus.ON_HOLD:
            raise WorkflowError("Only an on-hold invoice can be released")
        target = InvoiceStatus.REVIEW_REQUIRED
    elif action == WorkflowAction.QUEUE_PAYMENT:
        if current != InvoiceStatus.APPROVED:
            raise WorkflowError("Only approved invoices can be queued for payment")
        target = InvoiceStatus.AWAITING_PAYMENT
    elif action == WorkflowAction.MARK_DUPLICATE:
        if current in {InvoiceStatus.PAID, InvoiceStatus.REJECTED}:
            raise WorkflowError(f"Cannot mark an invoice {current.value} as duplicate")
        target = InvoiceStatus.DUPLICATE
    elif action == WorkflowAction.MARK_PAID:
        if current not in {InvoiceStatus.APPROVED, InvoiceStatus.AWAITING_PAYMENT}:
            raise WorkflowError("Only approved invoices can be marked paid")
        target = InvoiceStatus.PAID
        invoice.outstanding_amount = Decimal("0")
    else:
        raise WorkflowError(f"Unsupported workflow action: {action.value}")

    invoice.status = target.value
    if target in {InvoiceStatus.APPROVED, InvoiceStatus.AWAITING_PAYMENT, InvoiceStatus.PAID}:
        invoice.review_reason = None
    session.add(
        WorkflowEvent(
            invoice_id=invoice.id,
            tenant_id=invoice.tenant_id,
            action=action.value,
            from_status=current.value,
            to_status=target.value,
            actor=actor,
            comment=comment,
        )
    )
    await session.flush()
    return invoice


async def record_payment(
    session: AsyncSession,
    invoice: Invoice,
    *,
    amount: Decimal,
    payment_date: date,
    method: str,
    reference: str | None,
    notes: str | None,
    actor: str,
) -> Payment:
    if invoice.status not in {InvoiceStatus.APPROVED.value, InvoiceStatus.AWAITING_PAYMENT.value}:
        raise WorkflowError("Payments can only be recorded for approved invoices")
    if amount > decimal_value(invoice.outstanding_amount):
        raise WorkflowError("Payment cannot exceed the invoice outstanding balance")
    payment = Payment(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        amount=amount,
        payment_date=payment_date,
        method=method,
        reference=reference,
        notes=notes,
    )
    session.add(payment)
    await session.flush()
    previous = invoice.status
    invoice.status = InvoiceStatus.AWAITING_PAYMENT.value
    await recalculate_outstanding(session, invoice)
    if invoice.status == InvoiceStatus.PAID.value:
        session.add(
            WorkflowEvent(
                invoice_id=invoice.id,
                tenant_id=invoice.tenant_id,
                action=WorkflowAction.MARK_PAID.value,
                from_status=previous,
                to_status=InvoiceStatus.PAID.value,
                actor=actor,
                comment="Payment balance reached zero",
            )
        )
    return payment


async def get_invoice_bundle(session: AsyncSession, invoice_id: str, tenant_id: str) -> dict | None:
    invoice = await session.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
    )
    if invoice is None:
        return None
    document = await session.scalar(select(Document).where(Document.id == invoice.document_id))
    vendor = (
        await session.scalar(
            select(Vendor).where(Vendor.id == invoice.vendor_id, Vendor.tenant_id == tenant_id)
        )
        if invoice.vendor_id
        else None
    )
    vendor_metrics = {"invoice_count": 0, "total_spend": Decimal("0"), "outstanding": Decimal("0")}
    if vendor is not None:
        vendor_metrics["invoice_count"] = (
            await session.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.vendor_id == vendor.id, Invoice.tenant_id == tenant_id
                )
            )
            or 0
        )
        vendor_metrics["total_spend"] = decimal_value(
            await session.scalar(
                select(func.coalesce(func.sum(Invoice.grand_total), 0)).where(
                    Invoice.vendor_id == vendor.id, Invoice.tenant_id == tenant_id
                )
            )
        )
        vendor_metrics["outstanding"] = decimal_value(
            await session.scalar(
                select(func.coalesce(func.sum(Invoice.outstanding_amount), 0)).where(
                    Invoice.vendor_id == vendor.id, Invoice.tenant_id == tenant_id
                )
            )
        )
    items = list(
        await session.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
    )
    taxes = list(
        await session.scalars(select(InvoiceTax).where(InvoiceTax.invoice_id == invoice.id))
    )
    validations = list(
        await session.scalars(
            select(InvoiceValidation)
            .where(InvoiceValidation.invoice_id == invoice.id)
            .order_by(InvoiceValidation.created_at)
        )
    )
    risks = list(
        await session.scalars(
            select(InvoiceRiskFlag)
            .where(InvoiceRiskFlag.invoice_id == invoice.id)
            .order_by(InvoiceRiskFlag.points.desc())
        )
    )
    payments = list(
        await session.scalars(
            select(Payment)
            .where(Payment.invoice_id == invoice.id)
            .order_by(Payment.payment_date.desc())
        )
    )
    workflow = list(
        await session.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.invoice_id == invoice.id)
            .order_by(WorkflowEvent.created_at)
        )
    )
    corrections = []
    if document is not None:
        corrections = list(
            await session.scalars(
                select(AuditEntryModel)
                .where(
                    AuditEntryModel.document_id == document.id,
                    AuditEntryModel.tenant_id == tenant_id,
                )
                .order_by(AuditEntryModel.timestamp)
            )
        )
    return {
        "invoice": invoice,
        "document": document,
        "vendor": vendor,
        "vendor_metrics": vendor_metrics,
        "items": items,
        "taxes": taxes,
        "validations": validations,
        "risks": risks,
        "payments": payments,
        "workflow": workflow,
        "corrections": corrections,
    }


async def dashboard_summary(session: AsyncSession, tenant_id: str) -> APDashboardSummary:
    invoices = list(await session.scalars(select(Invoice).where(Invoice.tenant_id == tenant_id)))
    today = date.today()
    week_end = today + timedelta(days=(6 - today.weekday()))
    summary = APDashboardSummary()
    summary.total_invoices = len(invoices)
    summary.processing_invoices = (
        await session.scalar(
            select(func.count(Document.id)).where(
                Document.tenant_id == tenant_id,
                Document.status.in_(
                    [
                        status.value
                        for status in DocumentStatus
                        if status not in {DocumentStatus.COMPLETED, DocumentStatus.FAILED}
                    ]
                ),
            )
        )
        or 0
    )
    confidences = [invoice.overall_confidence for invoice in invoices]
    summary.average_confidence = (
        round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    )
    for invoice in invoices:
        amount = decimal_value(invoice.outstanding_amount)
        if invoice.status == InvoiceStatus.REVIEW_REQUIRED.value:
            summary.review_invoices += 1
        elif invoice.status == InvoiceStatus.APPROVED.value:
            summary.approved_invoices += 1
        elif invoice.status == InvoiceStatus.AWAITING_PAYMENT.value:
            summary.awaiting_payment_invoices += 1
        elif invoice.status == InvoiceStatus.PAID.value:
            summary.paid_invoices += 1
        elif invoice.status == InvoiceStatus.REJECTED.value:
            summary.rejected_invoices += 1
        elif invoice.status == InvoiceStatus.DUPLICATE.value:
            summary.duplicate_invoices += 1
        elif invoice.status == InvoiceStatus.ON_HOLD.value:
            summary.on_hold_invoices += 1
        if invoice.risk_level == RiskLevel.HIGH.value:
            summary.high_risk_count += 1
        if invoice.status not in {
            InvoiceStatus.PAID.value,
            InvoiceStatus.REJECTED.value,
            InvoiceStatus.DUPLICATE.value,
        }:
            summary.outstanding_total += amount
        if invoice.status in {
            InvoiceStatus.PAID.value,
            InvoiceStatus.REJECTED.value,
            InvoiceStatus.DUPLICATE.value,
        }:
            continue
        if invoice.due_date and amount > 0:
            if invoice.due_date < today:
                summary.overdue_total += amount
            elif invoice.due_date <= week_end:
                summary.due_this_week += amount

    aging = {
        label: [Decimal("0"), 0]
        for label in ("Current", "1–30 days", "31–60 days", "61–90 days", "90+ days")
    }
    for invoice in invoices:
        amount = decimal_value(invoice.outstanding_amount)
        if (
            invoice.status
            in {
                InvoiceStatus.PAID.value,
                InvoiceStatus.REJECTED.value,
                InvoiceStatus.DUPLICATE.value,
            }
            or amount <= 0
            or not invoice.due_date
        ):
            continue
        days_overdue = max(0, (today - invoice.due_date).days)
        label = (
            "Current"
            if days_overdue == 0
            else "1–30 days"
            if days_overdue <= 30
            else "31–60 days"
            if days_overdue <= 60
            else "61–90 days"
            if days_overdue <= 90
            else "90+ days"
        )
        aging[label][0] += amount
        aging[label][1] += 1
    summary.aging = [
        AgingBucket(label=label, amount=value[0], count=value[1]) for label, value in aging.items()
    ]
    tax_total = await session.scalar(
        select(func.coalesce(func.sum(InvoiceTax.amount), 0))
        .join(Invoice, InvoiceTax.invoice_id == Invoice.id)
        .where(Invoice.tenant_id == tenant_id)
    )
    summary.total_tax = decimal_value(tax_total)
    return summary
