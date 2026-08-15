"""Accounts-payable API routes."""

from __future__ import annotations

import copy
import csv
import io
import json
import math
import re
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import deps
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.security import get_tenant_id, verify_auth
from app.domain.entities import (
    AuditEntryModel,
    Document,
    GoodsReceipt,
    GoodsReceiptItem,
    Invoice,
    InvoiceTax,
    OCRToken,
    PurchaseOrder,
    PurchaseOrderItem,
    Vendor,
    WorkflowEvent,
)
from app.domain.schemas import (
    AgingBucket,
    APAnalyticsResponse,
    APDashboardSummary,
    AuditEntry,
    DocumentStatus,
    GoodsReceiptCreateRequest,
    GoodsReceiptResponse,
    GSTSummaryResponse,
    ImportResult,
    InvoiceActionRequest,
    InvoiceFieldUpdateRequest,
    InvoiceItemResponse,
    InvoiceListResponse,
    InvoiceQuestionRequest,
    InvoiceQuestionResponse,
    InvoiceResponse,
    InvoiceStatus,
    InvoiceTaxResponse,
    MatchStatus,
    PaymentCreateRequest,
    PaymentDueResponse,
    PaymentResponse,
    PaymentStatus,
    ProviderStatusResponse,
    PurchaseOrderCreateRequest,
    PurchaseOrderResponse,
    RiskFlagResponse,
    RiskLevel,
    ValidationResultResponse,
    VendorAnalytics,
    VendorCreateRequest,
    VendorDetailResponse,
    VendorInvoiceSummary,
    VendorResponse,
    VolumePoint,
    WorkflowEventResponse,
)
from app.services.ap_service import (
    WorkflowError,
    apply_workflow_action,
    dashboard_summary,
    decimal_value,
    get_invoice_bundle,
    normalize_text,
    parse_date,
    project_document,
    record_payment,
)
from app.services.corrections import audit_value
from app.services.invoice_assistant import answer_invoice_question

router = APIRouter(prefix="", tags=["accounts-payable"], dependencies=[Depends(verify_auth)])


def _vendor_response(vendor: Vendor | None) -> VendorResponse | None:
    if vendor is None:
        return None
    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        gstin=vendor.gstin,
        pan=vendor.pan,
        address=vendor.address,
        state=vendor.state,
        email=vendor.email,
        phone=vendor.phone,
        bank_name=vendor.bank_name,
        bank_account=vendor.bank_account,
        ifsc=vendor.ifsc,
        payment_terms=vendor.payment_terms,
        created_at=vendor.created_at,
    )


def _invoice_response(bundle: dict) -> InvoiceResponse:
    invoice: Invoice = bundle["invoice"]
    document: Document | None = bundle["document"]
    extraction = None
    if document and document.extraction_result:
        from app.domain.schemas import InvoiceExtraction

        extraction = InvoiceExtraction.model_validate(document.extraction_result)
    vendor_response = _vendor_response(bundle["vendor"])
    if vendor_response is not None:
        vendor_metrics = bundle.get("vendor_metrics", {})
        vendor_response.invoice_count = vendor_metrics.get("invoice_count", 0)
        vendor_response.total_spend = vendor_metrics.get("total_spend", Decimal("0"))
        vendor_response.outstanding = vendor_metrics.get("outstanding", Decimal("0"))
    return InvoiceResponse(
        id=invoice.id,
        document_id=invoice.document_id,
        filename=document.filename if document else None,
        preview_url=f"/api/v1/documents/{invoice.document_id}/preview"
        if document and document.file_path
        else None,
        page_count=document.page_count if document else 1,
        processing_status=DocumentStatus(document.status) if document else None,
        status=InvoiceStatus(invoice.status),
        review_reason=invoice.review_reason,
        invoice_number=invoice.invoice_number,
        duplicate_fingerprint=invoice.duplicate_fingerprint,
        invoice_date=invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        due_date=invoice.due_date.isoformat() if invoice.due_date else None,
        po_number=invoice.po_number,
        currency=invoice.currency,
        subtotal=invoice.subtotal,
        discount_total=invoice.discount_total,
        taxable_amount=invoice.taxable_amount,
        tax_total=invoice.tax_total,
        cgst=invoice.cgst,
        sgst=invoice.sgst,
        igst=invoice.igst,
        grand_total=invoice.grand_total,
        outstanding_amount=invoice.outstanding_amount,
        overall_confidence=invoice.overall_confidence,
        confidence_score=invoice.confidence_score,
        ocr_text=invoice.ocr_text,
        risk_score=invoice.risk_score,
        risk_level=RiskLevel(invoice.risk_level),
        match_status=MatchStatus(invoice.match_status),
        match_details=invoice.match_details or {},
        vendor=vendor_response,
        extraction=extraction,
        standardized_invoice=extraction.standardized_invoice or extraction.to_standard()
        if extraction
        else None,
        items=[
            InvoiceItemResponse(
                id=item.id,
                description=item.description,
                sku=item.sku,
                hsn=item.hsn,
                sac=item.sac,
                hsn_sac=item.hsn_sac,
                quantity=item.quantity,
                unit=item.unit,
                unit_price=item.unit_price,
                rate=item.rate,
                discount=item.discount,
                taxable_value=item.taxable_value,
                gst_rate=item.gst_rate,
                tax_amount=item.tax_amount,
                tax=item.tax,
                line_total=item.line_total,
                confidence=item.confidence,
            )
            for item in bundle["items"]
        ],
        taxes=[
            InvoiceTaxResponse(
                id=tax.id,
                tax_type=tax.tax_type,
                rate_percent=tax.rate_percent,
                amount=tax.amount,
            )
            for tax in bundle["taxes"]
        ],
        validations=[
            ValidationResultResponse(
                id=validation.id,
                rule=validation.rule,
                passed=validation.passed,
                severity=validation.severity,
                message=validation.message,
                details=validation.details or {},
                created_at=validation.created_at,
            )
            for validation in bundle["validations"]
        ],
        risk_flags=[
            RiskFlagResponse(
                id=flag.id,
                code=flag.code,
                points=flag.points,
                level=flag.level,
                message=flag.message,
                resolved=flag.resolved,
                details=flag.details or {},
                created_at=flag.created_at,
            )
            for flag in bundle["risks"]
        ],
        payments=[
            PaymentResponse(
                id=payment.id,
                invoice_id=payment.invoice_id,
                amount=payment.amount,
                payment_date=payment.payment_date.isoformat(),
                method=payment.method,
                reference=payment.reference,
                status=PaymentStatus(payment.status),
                notes=payment.notes,
                created_at=payment.created_at,
            )
            for payment in bundle["payments"]
        ],
        workflow=[
            WorkflowEventResponse(
                id=event.id,
                invoice_id=event.invoice_id,
                action=event.action,
                from_status=event.from_status,
                to_status=event.to_status,
                actor=event.actor,
                comment=event.comment,
                created_at=event.created_at,
            )
            for event in bundle["workflow"]
        ],
        corrections=[
            AuditEntry(
                id=entry.id,
                document_id=entry.document_id,
                field_path=entry.field_path,
                old_value=entry.old_value,
                new_value=entry.new_value,
                corrected_by=entry.corrected_by,
                timestamp=entry.timestamp,
                predicted=entry.old_value,
                correct=entry.new_value,
            )
            for entry in bundle.get("corrections", [])
        ],
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


def _search_amount(value: str) -> Decimal | None:
    """Parse an exact amount search such as ``₹50,000`` or ``INR 50000``."""

    cleaned = re.sub(r"(?i)(?:inr|rs\.?)", "", value).replace("₹", "")
    cleaned = cleaned.replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _search_date(value: str) -> date | None:
    """Parse only date-shaped search terms, avoiding invoice-number false hits."""

    text = value.strip()
    date_patterns = (
        r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}",
        r"\d{1,2}[-/.]\d{1,2}[-/.]\d{4}",
        r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}",
        r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}",
    )
    if not any(re.fullmatch(pattern, text) for pattern in date_patterns):
        return None
    return parse_date(text)


def _compact_gstin_search(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", value).casefold()
    for prefix in ("gstin", "gst"):
        if compact.startswith(prefix):
            return compact[len(prefix) :]
    return compact


async def _require_invoice(session: AsyncSession, invoice_id: str, tenant_id: str) -> Invoice:
    invoice = await session.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id)
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.get("/dashboard/summary", response_model=APDashboardSummary)
async def get_ap_dashboard_summary(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    return await dashboard_summary(db, tenant_id)


@router.get("/analytics/ap", response_model=APAnalyticsResponse)
async def get_ap_analytics(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    summary = await dashboard_summary(db, tenant_id)
    invoices = list(await db.scalars(select(Invoice).where(Invoice.tenant_id == tenant_id)))
    vendors = list(await db.scalars(select(Vendor).where(Vendor.tenant_id == tenant_id)))
    vendor_metrics = []
    for vendor in vendors:
        vendor_invoices = [invoice for invoice in invoices if invoice.vendor_id == vendor.id]
        vendor_metrics.append(
            VendorAnalytics(
                vendor_name=vendor.name,
                document_count=len(vendor_invoices),
                total_spend=sum(
                    (decimal_value(invoice.grand_total) for invoice in vendor_invoices),
                    Decimal("0"),
                ),
                average_confidence=round(
                    sum(invoice.overall_confidence for invoice in vendor_invoices)
                    / len(vendor_invoices),
                    3,
                )
                if vendor_invoices
                else 0.0,
            )
        )
    trend_groups: dict[str, list[Invoice]] = {}
    for invoice in invoices:
        if invoice.created_at:
            trend_groups.setdefault(invoice.created_at.date().isoformat(), []).append(invoice)
    trends = [
        VolumePoint(
            date=day,
            document_count=len(group),
            average_confidence=round(
                sum(invoice.overall_confidence for invoice in group) / len(group), 3
            ),
        )
        for day, group in sorted(trend_groups.items())
    ]
    return APAnalyticsResponse(
        summary=summary,
        vendors=sorted(vendor_metrics, key=lambda item: item.total_spend, reverse=True),
        trends=trends,
    )


@router.get("/provider/status", response_model=ProviderStatusResponse)
async def get_provider_status(
    settings: Settings = Depends(get_settings),
    vlm_client=Depends(deps.get_vlm_client),
):
    available = False
    ocr_label = settings.ocr_engine.value
    layout_label = getattr(settings, "layout_engine", "spatial-rules")
    parser_label = getattr(settings, "document_parser", "pymupdf")
    engine_labels = list(dict.fromkeys((ocr_label, layout_label)))
    deterministic_provider = " + ".join((*engine_labels, "rules"))
    active_provider = deterministic_provider
    if vlm_client is not None:
        available = await vlm_client.health_check()
        if available:
            active_provider = " + ".join((*engine_labels, vlm_client.name))
    configured_provider = settings.vlm_provider.value
    message = (
        f"{active_provider} is available; {parser_label} document parsing is configured."
        if available
        else (
            f"{deterministic_provider} is active; "
            f"optional {configured_provider} local AI is not available."
        )
    )
    return ProviderStatusResponse(
        profile=getattr(settings, "pipeline_profile", "local-full"),
        ocr_engine=ocr_label,
        layout_engine=layout_label,
        document_parser=parser_label,
        configured_provider=configured_provider,
        active_provider=active_provider,
        available=available,
        message=message,
    )


@router.get("/analytics/ap/vendor-spend", response_model=list[VendorAnalytics])
async def get_vendor_spend(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    return (await get_ap_analytics(db, tenant_id)).vendors


@router.get("/analytics/ap/trends", response_model=list[VolumePoint])
async def get_ap_trends(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    return (await get_ap_analytics(db, tenant_id)).trends


@router.get("/analytics/ap/gst", response_model=GSTSummaryResponse)
async def get_gst_summary(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    rows = list(
        await db.execute(
            select(InvoiceTax.tax_type, InvoiceTax.amount)
            .join(Invoice, InvoiceTax.invoice_id == Invoice.id)
            .where(Invoice.tenant_id == tenant_id)
        )
    )
    by_type: dict[str, Decimal] = {}
    for tax_type, amount in rows:
        by_type[tax_type] = by_type.get(tax_type, Decimal("0")) + decimal_value(amount)
    invoice_count = await db.scalar(
        select(func.count(func.distinct(Invoice.id)))
        .join(InvoiceTax, InvoiceTax.invoice_id == Invoice.id)
        .where(Invoice.tenant_id == tenant_id)
    )
    return GSTSummaryResponse(
        total_tax=sum(by_type.values(), Decimal("0")),
        invoice_count=invoice_count or 0,
        by_type=by_type,
    )


@router.get("/analytics/ap/aging", response_model=list[AgingBucket])
async def get_ap_aging(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    return (await dashboard_summary(db, tenant_id)).aging


@router.get("/risk-queue", response_model=InvoiceListResponse)
async def get_risk_queue(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    invoices = list(
        await db.scalars(
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id, Invoice.risk_level.in_(["medium", "high"]))
            .order_by(Invoice.risk_score.desc(), Invoice.created_at.desc())
        )
    )
    responses = []
    for invoice in invoices:
        bundle = await get_invoice_bundle(db, invoice.id, tenant_id)
        if bundle:
            responses.append(_invoice_response(bundle))
    return InvoiceListResponse(
        invoices=responses,
        total=len(responses),
        page=1,
        page_size=len(responses) or 1,
        total_pages=1 if responses else 0,
    )


def _invoice_export_rows(responses: list[InvoiceResponse]) -> list[list[object]]:
    rows: list[list[object]] = [
        [
            "invoice_number",
            "vendor",
            "invoice_date",
            "due_date",
            "status",
            "grand_total",
            "outstanding",
            "risk_score",
            "po_number",
        ]
    ]
    for item in responses:
        rows.append(
            [
                item.invoice_number or "",
                item.vendor.name if item.vendor else "",
                item.invoice_date or "",
                item.due_date or "",
                item.status.value,
                str(item.grand_total or ""),
                str(item.outstanding_amount),
                item.risk_score,
                item.po_number or "",
            ]
        )
    return rows


def _serialize_invoice_export(
    responses: list[InvoiceResponse], format: str, filename_prefix: str
) -> Response:
    if format == "json":
        payload = json.dumps(
            [item.model_dump(mode="json") for item in responses], default=str, indent=2
        )
        return Response(
            payload,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename_prefix}.json"},
        )

    rows = _invoice_export_rows(responses)
    if format == "csv":
        output = io.StringIO(newline="")
        csv.writer(output).writerows(rows)
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename_prefix}.csv"},
        )

    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="XLSX export requires the openpyxl dependency"
        ) from exc
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoices"
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    return Response(
        stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename_prefix}.xlsx"},
    )


@router.get("/invoices/export")
async def export_invoices(
    format: str = Query("csv", pattern="^(csv|json|xlsx)$"),
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    query = (
        select(Invoice).where(Invoice.tenant_id == tenant_id).order_by(Invoice.created_at.desc())
    )
    if status_filter:
        query = query.where(Invoice.status == status_filter)
    invoices = list(await db.scalars(query))
    bundles = [await get_invoice_bundle(db, invoice.id, tenant_id) for invoice in invoices]
    responses = [_invoice_response(bundle) for bundle in bundles if bundle]
    return _serialize_invoice_export(responses, format, "invoices")


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    risk: str | None = None,
    vendor_id: str | None = None,
    overdue: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount: Decimal | None = Query(None, ge=0),
    max_amount: Decimal | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    query = select(Invoice).where(Invoice.tenant_id == tenant_id)
    if status_filter:
        query = query.where(Invoice.status == status_filter)
    if risk:
        query = query.where(Invoice.risk_level == risk)
    if vendor_id:
        query = query.where(Invoice.vendor_id == vendor_id)
    if overdue:
        query = query.where(Invoice.due_date < date.today(), Invoice.outstanding_amount > 0)
    if date_from:
        query = query.where(Invoice.invoice_date >= date_from)
    if date_to:
        query = query.where(Invoice.invoice_date <= date_to)
    if min_amount is not None:
        query = query.where(Invoice.grand_total >= min_amount)
    if max_amount is not None:
        query = query.where(Invoice.grand_total <= max_amount)
    if search:
        amount_search = _search_amount(search)
        date_search = _search_date(search)
        gstin_search = _compact_gstin_search(search)
        vendor_ids = select(Vendor.id).where(
            Vendor.tenant_id == tenant_id,
            or_(
                Vendor.name.ilike(f"%{search}%"),
                Vendor.gstin.ilike(f"%{search}%"),
                Vendor.gstin.ilike(f"%{gstin_search}%") if gstin_search else False,
            ),
        )
        search_clauses = [
            Invoice.invoice_number.ilike(f"%{search}%"),
            Invoice.po_number.ilike(f"%{search}%"),
            Invoice.status.ilike(f"%{search}%"),
            Invoice.vendor_id.in_(vendor_ids),
        ]
        if amount_search is not None:
            search_clauses.extend(
                [
                    Invoice.grand_total == amount_search,
                    Invoice.outstanding_amount == amount_search,
                ]
            )
        if date_search is not None:
            search_clauses.extend(
                [Invoice.invoice_date == date_search, Invoice.due_date == date_search]
            )
        query = query.where(or_(*search_clauses))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    invoices = list(
        await db.scalars(
            query.order_by(Invoice.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    responses = []
    for invoice in invoices:
        bundle = await get_invoice_bundle(db, invoice.id, tenant_id)
        if bundle:
            responses.append(_invoice_response(bundle))
    return InvoiceListResponse(
        invoices=responses,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total else 0,
    )


@router.post("/invoices/{invoice_id}/qa", response_model=InvoiceQuestionResponse)
async def ask_invoice_question(
    invoice_id: str,
    request: InvoiceQuestionRequest,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
    vlm_client=Depends(deps.get_vlm_client),
):
    bundle = await get_invoice_bundle(db, invoice_id, tenant_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    question = request.question.strip()
    invoice = bundle["invoice"]
    tokens = list(
        await db.scalars(
            select(OCRToken.text)
            .where(OCRToken.document_id == invoice.document_id, OCRToken.tenant_id == tenant_id)
            .order_by(OCRToken.page, OCRToken.y, OCRToken.x)
            .limit(500)
        )
    )
    ocr_text = "\n".join(tokens)[:12000]
    return await answer_invoice_question(
        question,
        bundle,
        ocr_text,
        assistant_client=vlm_client,
    )


@router.get("/invoices/{invoice_id}/export")
async def export_invoice(
    invoice_id: str,
    format: str = Query("json", pattern="^(csv|json|xlsx)$"),
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    bundle = await get_invoice_bundle(db, invoice_id, tenant_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _serialize_invoice_export([_invoice_response(bundle)], format, f"invoice-{invoice_id}")


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    bundle = await get_invoice_bundle(db, invoice_id, tenant_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _invoice_response(bundle)


@router.get("/documents/{document_id}/invoice", response_model=InvoiceResponse)
async def get_invoice_for_document(
    document_id: str,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    invoice = await db.scalar(
        select(Invoice).where(Invoice.document_id == document_id, Invoice.tenant_id == tenant_id)
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="AP invoice is not available yet")
    bundle = await get_invoice_bundle(db, invoice.id, tenant_id)
    return _invoice_response(bundle)


@router.post("/invoices/{invoice_id}/actions", response_model=InvoiceResponse)
async def invoice_action(
    invoice_id: str,
    request: InvoiceActionRequest,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    invoice = await _require_invoice(db, invoice_id, tenant_id)
    try:
        await apply_workflow_action(
            db,
            invoice,
            request.action,
            actor=request.actor,
            comment=request.comment,
            override=request.override,
        )
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    bundle = await get_invoice_bundle(db, invoice_id, tenant_id)
    return _invoice_response(bundle)


@router.patch("/invoices/{invoice_id}/fields", response_model=InvoiceResponse)
async def update_invoice_field(
    invoice_id: str,
    request: InvoiceFieldUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    invoice = await _require_invoice(db, invoice_id, tenant_id)
    document = await db.scalar(
        select(Document).where(Document.id == invoice.document_id, Document.tenant_id == tenant_id)
    )
    if document is None or not document.extraction_result:
        raise HTTPException(status_code=409, detail="Invoice has no extraction payload to edit")
    allowed = {
        "invoice_number.value",
        "invoice_date",
        "due_date",
        "po_reference.value",
        "payment_terms",
        "vendor.name.value",
        "vendor.address.value",
        "vendor.gstin.value",
        "vendor.pan.value",
        "vendor.email.value",
        "vendor.phone.value",
        "vendor.bank_name.value",
        "vendor.bank_account.value",
        "vendor.ifsc.value",
        "buyer.name.value",
        "buyer.address.value",
        "buyer.billing_address.value",
        "buyer.shipping_address.value",
        "buyer.gstin.value",
        "buyer.pan.value",
        "place_of_supply",
        "subtotal",
        "discount_total",
        "tax_total",
        "grand_total",
        "currency",
    }
    if request.field_path not in allowed:
        raise HTTPException(status_code=400, detail=f"Field is not editable: {request.field_path}")
    from app.domain.schemas import InvoiceExtraction

    extraction_payload = copy.deepcopy(document.extraction_result)
    current = extraction_payload
    parts = request.field_path.split(".")
    for part in parts[:-1]:
        if current.get(part) is None:
            current[part] = {"value": None, "confidence": 0.0, "source": "ocr_regex"}
        current = current[part]
    server_old_value = current.get(parts[-1])
    current[parts[-1]] = request.new_value
    if parts[-1] == "value":
        current["source"] = "human_corrected"
        current["confidence"] = 1.0
    try:
        validated = InvoiceExtraction.model_validate(extraction_payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid corrected value: {exc}") from exc
    audit = AuditEntryModel(
        document_id=document.id,
        tenant_id=tenant_id,
        field_path=request.field_path,
        # The stored extraction, not a browser payload, is the prediction
        # used for future training examples.
        old_value=audit_value(server_old_value),
        new_value=audit_value(request.new_value) or "",
        corrected_by=request.corrected_by,
    )
    db.add(audit)
    document.extraction_result = validated.model_dump(mode="json")
    document.overall_confidence = validated.overall_confidence
    document.vendor_name = validated.vendor.name.value
    document.grand_total = (
        float(validated.grand_total) if validated.grand_total is not None else None
    )
    document.currency = validated.currency
    await project_document(db, document)
    await db.commit()
    bundle = await get_invoice_bundle(db, invoice_id, tenant_id)
    return _invoice_response(bundle)


@router.post("/invoices/{invoice_id}/payments", response_model=InvoiceResponse)
async def add_invoice_payment(
    invoice_id: str,
    request: PaymentCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    invoice = await _require_invoice(db, invoice_id, tenant_id)
    payment_date = parse_date(request.payment_date)
    if payment_date is None:
        raise HTTPException(status_code=422, detail="payment_date must be a valid date")
    try:
        await record_payment(
            db,
            invoice,
            amount=request.amount,
            payment_date=payment_date,
            method=request.method,
            reference=request.reference,
            notes=request.notes,
            actor=request.actor,
        )
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    bundle = await get_invoice_bundle(db, invoice_id, tenant_id)
    return _invoice_response(bundle)


@router.get("/payments", response_model=list[PaymentDueResponse])
async def list_payments(
    overdue: bool = False,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    query = select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.outstanding_amount > 0)
    if overdue:
        query = query.where(Invoice.due_date < date.today())
    invoices = list(await db.scalars(query.order_by(Invoice.due_date)))
    output = []
    for invoice in invoices:
        vendor = (
            await db.scalar(select(Vendor).where(Vendor.id == invoice.vendor_id))
            if invoice.vendor_id
            else None
        )
        output.append(
            {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "vendor": vendor.name if vendor else None,
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                "grand_total": invoice.grand_total,
                "outstanding_amount": invoice.outstanding_amount,
                "status": invoice.status,
                "overdue": bool(invoice.due_date and invoice.due_date < date.today()),
            }
        )
    return output


@router.get("/payments/export")
async def export_payments(
    format: str = Query("csv", pattern="^(csv|json|xlsx)$"),
    overdue: bool = False,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    query = select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.outstanding_amount > 0)
    if overdue:
        query = query.where(Invoice.due_date < date.today())
    invoices = list(await db.scalars(query.order_by(Invoice.due_date)))
    rows = [
        [
            "invoice_number",
            "vendor",
            "due_date",
            "grand_total",
            "outstanding_amount",
            "status",
            "overdue",
        ]
    ]
    records = []
    for invoice in invoices:
        vendor = (
            await db.scalar(select(Vendor).where(Vendor.id == invoice.vendor_id))
            if invoice.vendor_id
            else None
        )
        record = {
            "invoice_number": invoice.invoice_number,
            "vendor": vendor.name if vendor else None,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "grand_total": invoice.grand_total,
            "outstanding_amount": invoice.outstanding_amount,
            "status": invoice.status,
            "overdue": bool(invoice.due_date and invoice.due_date < date.today()),
        }
        records.append(record)
        rows.append(
            [
                record["invoice_number"] or "",
                record["vendor"] or "",
                record["due_date"] or "",
                str(record["grand_total"] or ""),
                str(record["outstanding_amount"]),
                record["status"],
                record["overdue"],
            ]
        )
    if format == "json":
        return Response(
            json.dumps(records, default=str, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=payments.json"},
        )
    if format == "csv":
        output = io.StringIO(newline="")
        csv.writer(output).writerows(rows)
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=payments.csv"},
        )
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="XLSX export requires the openpyxl dependency"
        ) from exc
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Payments"
    for row in rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    return Response(
        stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=payments.xlsx"},
    )


@router.get("/invoices/{invoice_id}/events", response_model=list[WorkflowEventResponse])
async def invoice_workflow_events(
    invoice_id: str,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    await _require_invoice(db, invoice_id, tenant_id)
    events = list(
        await db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.invoice_id == invoice_id)
            .order_by(WorkflowEvent.created_at)
        )
    )
    return [
        WorkflowEventResponse(
            id=event.id,
            invoice_id=event.invoice_id,
            action=event.action,
            from_status=event.from_status,
            to_status=event.to_status,
            actor=event.actor,
            comment=event.comment,
            created_at=event.created_at,
        )
        for event in events
    ]


@router.get("/vendors", response_model=list[VendorResponse])
async def list_vendors(
    search: str | None = None,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    query = select(Vendor).where(Vendor.tenant_id == tenant_id).order_by(Vendor.name)
    if search:
        query = query.where(
            or_(Vendor.name.ilike(f"%{search}%"), Vendor.gstin.ilike(f"%{search}%"))
        )
    vendors = list(await db.scalars(query))
    output = []
    for vendor in vendors:
        count = (
            await db.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.vendor_id == vendor.id, Invoice.tenant_id == tenant_id
                )
            )
            or 0
        )
        spend = await db.scalar(
            select(func.coalesce(func.sum(Invoice.grand_total), 0)).where(
                Invoice.vendor_id == vendor.id, Invoice.tenant_id == tenant_id
            )
        )
        outstanding = await db.scalar(
            select(func.coalesce(func.sum(Invoice.outstanding_amount), 0)).where(
                Invoice.vendor_id == vendor.id, Invoice.tenant_id == tenant_id
            )
        )
        item = _vendor_response(vendor)
        item.invoice_count = count
        item.total_spend = decimal_value(spend)
        item.outstanding = decimal_value(outstanding)
        output.append(item)
    return output


@router.get("/vendors/{vendor_id}", response_model=VendorDetailResponse)
async def get_vendor(
    vendor_id: str,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    vendor = await db.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.tenant_id == tenant_id)
    )
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    invoices = list(
        await db.scalars(
            select(Invoice)
            .where(Invoice.vendor_id == vendor.id, Invoice.tenant_id == tenant_id)
            .order_by(Invoice.invoice_date.desc().nullslast(), Invoice.created_at.desc())
        )
    )
    count = len(invoices)
    item = _vendor_response(vendor)
    assert item is not None
    item.invoice_count = count
    item.total_spend = sum(
        (decimal_value(invoice.grand_total) for invoice in invoices), Decimal("0")
    )
    item.outstanding = sum(
        (decimal_value(invoice.outstanding_amount) for invoice in invoices), Decimal("0")
    )
    return VendorDetailResponse(
        **item.model_dump(),
        invoices=[
            VendorInvoiceSummary(
                id=invoice.id,
                invoice_number=invoice.invoice_number,
                invoice_date=invoice.invoice_date.isoformat() if invoice.invoice_date else None,
                grand_total=invoice.grand_total,
                outstanding_amount=invoice.outstanding_amount,
                status=InvoiceStatus(invoice.status),
            )
            for invoice in invoices
        ],
    )


@router.post("/vendors", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    request: VendorCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Vendor name is required")
    vendor = Vendor(
        tenant_id=tenant_id,
        name=name,
        normalized_name=normalize_text(name),
        gstin=request.gstin,
        pan=request.pan,
        address=request.address,
        state=request.state,
        email=request.email,
        phone=request.phone,
        bank_name=request.bank_name,
        bank_account=request.bank_account,
        ifsc=request.ifsc,
        payment_terms=request.payment_terms,
    )
    db.add(vendor)
    await db.commit()
    return _vendor_response(vendor)


@router.post("/vendors/import", response_model=ImportResult)
async def import_vendors(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    raw = await file.read()
    try:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(status_code=400, detail="Vendor import must be a UTF-8 CSV") from exc
    errors = []
    accepted = 0
    for index, row in enumerate(rows, start=2):
        name = (row.get("name") or row.get("vendor_name") or "").strip()
        if not name:
            errors.append(f"Row {index}: name is required")
            continue
        gstin = row.get("gstin") or None
        vendor = None
        if gstin:
            vendor = await db.scalar(
                select(Vendor).where(Vendor.tenant_id == tenant_id, Vendor.gstin == gstin)
            )
        if vendor is None:
            vendor = await db.scalar(
                select(Vendor).where(
                    Vendor.tenant_id == tenant_id,
                    Vendor.normalized_name == normalize_text(name),
                )
            )
        if vendor is None:
            vendor = Vendor(
                tenant_id=tenant_id,
                name=name,
                normalized_name=normalize_text(name),
            )
            db.add(vendor)
        vendor.name = name
        vendor.normalized_name = normalize_text(name)
        vendor.gstin = gstin or vendor.gstin
        vendor.pan = (row.get("pan") or None) or vendor.pan
        vendor.address = (row.get("address") or None) or vendor.address
        vendor.state = (row.get("state") or None) or vendor.state
        vendor.email = (row.get("email") or None) or vendor.email
        vendor.phone = (row.get("phone") or None) or vendor.phone
        vendor.bank_name = (row.get("bank_name") or None) or vendor.bank_name
        vendor.bank_account = (row.get("bank_account") or None) or vendor.bank_account
        vendor.ifsc = (row.get("ifsc") or None) or vendor.ifsc
        vendor.payment_terms = (row.get("payment_terms") or None) or vendor.payment_terms
        accepted += 1
    await db.commit()
    return ImportResult(accepted=accepted, rejected=len(errors), errors=errors)


@router.get("/purchase-orders", response_model=list[PurchaseOrderResponse])
async def list_purchase_orders(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    orders = list(
        await db.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.tenant_id == tenant_id)
            .order_by(PurchaseOrder.created_at.desc())
        )
    )
    return [await _purchase_order_response(db, order) for order in orders]


async def _purchase_order_response(db: AsyncSession, order: PurchaseOrder) -> PurchaseOrderResponse:
    vendor = (
        await db.scalar(
            select(Vendor).where(Vendor.id == order.vendor_id, Vendor.tenant_id == order.tenant_id)
        )
        if order.vendor_id
        else None
    )
    items = list(
        await db.scalars(
            select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == order.id)
        )
    )
    receipts = list(
        await db.scalars(
            select(GoodsReceipt)
            .where(GoodsReceipt.purchase_order_id == order.id)
            .order_by(GoodsReceipt.receipt_date.desc(), GoodsReceipt.created_at.desc())
        )
    )
    from app.domain.schemas import PurchaseOrderItemResponse

    return PurchaseOrderResponse(
        id=order.id,
        number=order.number,
        vendor=_vendor_response(vendor),
        vendor_id=order.vendor_id,
        status=order.status,
        order_date=order.order_date.isoformat() if order.order_date else None,
        expected_delivery=order.expected_delivery.isoformat() if order.expected_delivery else None,
        currency=order.currency,
        subtotal=order.subtotal,
        tax_total=order.tax_total,
        total=order.total,
        notes=order.notes,
        items=[
            PurchaseOrderItemResponse(
                id=item.id,
                description=item.description,
                hsn_sac=item.hsn_sac,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                line_total=item.line_total,
            )
            for item in items
        ],
        receipts=[
            GoodsReceiptResponse(
                id=receipt.id,
                purchase_order_id=receipt.purchase_order_id,
                receipt_number=receipt.receipt_number,
                receipt_date=receipt.receipt_date.isoformat(),
                status=receipt.status,
                notes=receipt.notes,
                created_at=receipt.created_at,
            )
            for receipt in receipts
        ],
        created_at=order.created_at,
    )


async def _create_purchase_order(
    db: AsyncSession, request: PurchaseOrderCreateRequest, tenant_id: str
) -> PurchaseOrder:
    vendor = None
    if request.vendor_id:
        vendor = await db.scalar(
            select(Vendor).where(Vendor.id == request.vendor_id, Vendor.tenant_id == tenant_id)
        )
    elif request.vendor_name:
        vendor = await db.scalar(
            select(Vendor).where(
                Vendor.tenant_id == tenant_id,
                Vendor.normalized_name == normalize_text(request.vendor_name),
            )
        )
    subtotal = sum(
        (
            item.line_total if item.line_total is not None else item.quantity * item.unit_price
            for item in request.items
        ),
        Decimal("0"),
    )
    order = PurchaseOrder(
        tenant_id=tenant_id,
        number=request.number,
        vendor_id=vendor.id if vendor else None,
        order_date=parse_date(request.order_date),
        expected_delivery=parse_date(request.expected_delivery),
        currency=request.currency,
        subtotal=subtotal,
        tax_total=request.tax_total,
        total=subtotal + request.tax_total,
        notes=request.notes,
    )
    db.add(order)
    await db.flush()
    for item in request.items:
        db.add(
            PurchaseOrderItem(
                purchase_order_id=order.id,
                description=item.description,
                hsn_sac=item.hsn_sac,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                line_total=item.line_total
                if item.line_total is not None
                else item.quantity * item.unit_price,
            )
        )
    return order


@router.post(
    "/purchase-orders", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED
)
async def create_purchase_order(
    request: PurchaseOrderCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    order = await _create_purchase_order(db, request, tenant_id)
    await db.commit()
    return await _purchase_order_response(db, order)


@router.post("/purchase-orders/import", response_model=ImportResult)
async def import_purchase_orders(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    raw = await file.read()
    errors: list[str] = []
    requests: list[PurchaseOrderCreateRequest] = []
    try:
        if file.filename and file.filename.lower().endswith(".json"):
            payload = json.loads(raw.decode("utf-8-sig"))
            records = (
                payload if isinstance(payload, list) else payload.get("purchase_orders", [payload])
            )
            for index, record in enumerate(records, start=1):
                try:
                    requests.append(PurchaseOrderCreateRequest.model_validate(record))
                except Exception as exc:
                    errors.append(f"Record {index}: {exc}")
        else:
            rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            for index, row in enumerate(rows, start=2):
                try:
                    requests.append(
                        PurchaseOrderCreateRequest.model_validate(
                            {
                                "number": row.get("number") or row.get("po_number"),
                                "vendor_name": row.get("vendor_name"),
                                "order_date": row.get("order_date"),
                                "expected_delivery": row.get("expected_delivery"),
                                "currency": row.get("currency") or "INR",
                                "tax_total": row.get("tax_total") or 0,
                                "notes": row.get("notes"),
                                "items": [
                                    {
                                        "description": row.get("description") or "Imported item",
                                        "quantity": row.get("quantity") or 0,
                                        "unit_price": row.get("unit_price") or 0,
                                        "tax_rate": row.get("tax_rate") or None,
                                        "line_total": row.get("line_total") or None,
                                    }
                                ],
                            }
                        )
                    )
                except Exception as exc:
                    errors.append(f"Row {index}: {exc}")
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        raise HTTPException(
            status_code=400, detail="PO import must be valid JSON or UTF-8 CSV"
        ) from exc

    accepted = 0
    for request in requests:
        try:
            async with db.begin_nested():
                await _create_purchase_order(db, request, tenant_id)
            accepted += 1
        except Exception as exc:
            errors.append(f"PO {request.number}: {exc}")
    await db.commit()
    return ImportResult(accepted=accepted, rejected=len(errors), errors=errors)


@router.post(
    "/purchase-orders/{purchase_order_id}/receipts",
    response_model=GoodsReceiptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_goods_receipt(
    purchase_order_id: str,
    request: GoodsReceiptCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    order = await db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.id == purchase_order_id, PurchaseOrder.tenant_id == tenant_id
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if request.purchase_order_id != purchase_order_id:
        raise HTTPException(status_code=400, detail="Receipt PO does not match the route PO")
    receipt = GoodsReceipt(
        tenant_id=tenant_id,
        purchase_order_id=order.id,
        receipt_number=request.receipt_number,
        receipt_date=parse_date(request.receipt_date) or date.today(),
        notes=request.notes,
    )
    db.add(receipt)
    await db.flush()
    for item in request.items:
        po_item = await db.scalar(
            select(PurchaseOrderItem).where(
                PurchaseOrderItem.id == item.purchase_order_item_id,
                PurchaseOrderItem.purchase_order_id == order.id,
            )
        )
        if po_item is None:
            raise HTTPException(
                status_code=400, detail="Receipt item is not on this purchase order"
            )
        db.add(
            GoodsReceiptItem(
                goods_receipt_id=receipt.id,
                purchase_order_item_id=item.purchase_order_item_id,
                quantity_received=item.quantity_received,
            )
        )
    await db.commit()
    return GoodsReceiptResponse(
        id=receipt.id,
        purchase_order_id=receipt.purchase_order_id,
        receipt_number=receipt.receipt_number,
        receipt_date=receipt.receipt_date.isoformat(),
        notes=receipt.notes,
        created_at=receipt.created_at,
    )
