"""
SQLAlchemy ORM entities — database table definitions.

These map 1:1 to database tables. The extraction result is stored as
a JSON column, keeping the relational structure for queryable metadata
while using JSON flexibility for the semi-structured extraction payload.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.compat import UTC
from app.core.database import Base
from app.domain.schemas import DocumentStatus


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class Document(Base):
    """
    Primary document table.

    Stores metadata about each uploaded document and its extraction result.
    The `extraction_result` column holds the full InvoiceExtraction as JSON.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=1)

    # Pipeline status
    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.PENDING.value, index=True
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    # Extraction result (full InvoiceExtraction JSON)
    extraction_result: Mapped[dict] = mapped_column(JSON, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_confidence: Mapped[float] = mapped_column(Float, nullable=True)
    processing_time_ms: Mapped[int] = mapped_column(Integer, nullable=True)

    # Extraction source tracking
    extraction_source: Mapped[str] = mapped_column(String(20), nullable=True)

    # Denormalised vendor name for efficient querying/filtering
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    grand_total: Mapped[float] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=True, default="INR")

    # Duplicate detection
    document_hash: Mapped[str] = mapped_column(String(64), nullable=True, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class AuditEntryModel(Base):
    """
    Audit trail for human corrections.

    Every time a user edits an extracted field through the dashboard,
    the before/after values are recorded here. This closes the
    human-in-the-loop feedback loop.
    """

    __tablename__ = "human_corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    field_path: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_by: Mapped[str] = mapped_column(String(100), default="user")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class User(Base):
    """Application user record used for actor attribution and future RBAC."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        Index("ix_users_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="ap_user")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class DocumentJob(Base):
    """Durable, database-backed work queue consumed by the local worker."""

    __tablename__ = "document_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, index=True
    )
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str] = mapped_column(String(100), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentEvent(Base):
    """Immutable processing timeline, published through Supabase Realtime."""

    __tablename__ = "document_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stage: Mapped[str] = mapped_column(String(40), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, index=True
    )


class OCRToken(Base):
    """Persisted word-level OCR evidence for source highlighting and audits."""

    __tablename__ = "ocr_tokens"
    __table_args__ = (Index("ix_ocr_tokens_document_page", "document_id", "page"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    x: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    y: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class DocumentPreprocessingArtifact(Base):
    """One persisted processed page paired with its original document source."""

    __tablename__ = "document_preprocessing_artifacts"
    __table_args__ = (
        UniqueConstraint("document_id", "page", name="uq_preprocessing_document_page"),
        Index("ix_preprocessing_artifacts_document_page", "document_id", "page"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    processed_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steps_applied: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    deskew_angle: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    orientation_correction: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# ── Accounts-payable domain ─────────────────────────────────────────


class Vendor(Base):
    """Supplier master record, scoped to a tenant."""

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "gstin", name="uq_vendors_tenant_gstin"),
        Index("ix_vendors_tenant_name", "tenant_id", "normalized_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ifsc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class Invoice(Base):
    """Canonical AP record projected from a processed document."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", name="uq_invoices_tenant_document"),
        Index("ix_invoices_tenant_status", "tenant_id", "status"),
        Index("ix_invoices_tenant_number", "tenant_id", "normalized_invoice_number"),
        Index("ix_invoices_tenant_duplicate_fingerprint", "tenant_id", "duplicate_fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    vendor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("vendors.id"), nullable=True
    )
    invoice_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    normalized_invoice_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    duplicate_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    po_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    discount_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    taxable_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tax_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    cgst: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    sgst: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    igst: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    grand_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    outstanding_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="review_required", nullable=False)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    match_status: Mapped[str] = mapped_column(String(30), default="not_applicable", nullable=False)
    match_details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hsn: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sac: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hsn_sac: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    taxable_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    gst_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class InvoiceTax(Base):
    __tablename__ = "invoice_taxes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id"), nullable=False, index=True
    )
    tax_type: Mapped[str] = mapped_column(String(30), nullable=False)
    rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)


class InvoiceValidation(Base):
    __tablename__ = "invoice_validations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id"), nullable=False, index=True
    )
    rule: Mapped[str] = mapped_column(String(80), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class InvoiceRiskFlag(Base):
    __tablename__ = "invoice_flags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class WorkflowEvent(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), default="local_user", nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, index=True
    )


class AIRun(Base):
    __tablename__ = "ai_extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False, index=True
    )
    invoice_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoices.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), default=Decimal("0"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_purchase_orders_tenant_number"),
        Index("ix_purchase_orders_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    number: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("vendors.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_delivery: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    tax_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    purchase_order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hsn_sac: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0.00"), nullable=False
    )


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    purchase_order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    receipt_number: Mapped[str] = mapped_column(String(120), nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="received", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class GoodsReceiptItem(Base):
    __tablename__ = "goods_receipt_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    goods_receipt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goods_receipts.id"), nullable=False, index=True
    )
    purchase_order_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_order_items.id"), nullable=False
    )
    quantity_received: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0"), nullable=False
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, default="local", index=True)
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(50), default="bank_transfer", nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Canonical names for callers that use the database design terminology. The
# legacy class names remain valid for the existing AP services and API code.
InvoiceFlag = InvoiceRiskFlag
AIExtraction = AIRun
HumanCorrection = AuditEntryModel
AuditLog = WorkflowEvent
