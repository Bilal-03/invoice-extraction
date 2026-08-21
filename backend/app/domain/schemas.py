"""
Pydantic v2 schemas — the single source of truth for data shapes.

These models serve triple duty:
  1. API request/response contracts (FastAPI auto-generates OpenAPI from these)
  2. Database serialisation boundary (stored as JSON in the extraction_result column)
  3. Frontend TypeScript types (generated from the OpenAPI spec)
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from app.core.compat import StrEnum

# ── Enums ────────────────────────────────────────────────────────────


class DocumentStatus(StrEnum):
    """Processing pipeline status state machine."""

    PENDING = "pending"
    PREPROCESSING = "preprocessing"
    OCR = "ocr"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


class InvoiceStatus(StrEnum):
    """Accounts-payable lifecycle, separate from document processing."""

    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    ON_HOLD = "on_hold"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MatchStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    MATCHED = "matched"
    PARTIAL = "partial"
    MISMATCH = "mismatch"


class PaymentStatus(StrEnum):
    CONFIRMED = "confirmed"
    VOID = "void"


class WorkflowAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    HOLD = "hold"
    RELEASE = "release"
    QUEUE_PAYMENT = "queue_payment"
    MARK_DUPLICATE = "mark_duplicate"
    MARK_PAID = "mark_paid"


class TaxType(StrEnum):
    """Supported tax classification types."""

    GST = "GST"
    CGST = "CGST"
    SGST = "SGST"
    CGST_SGST = "CGST_SGST"
    IGST = "IGST"
    CESS = "CESS"
    VAT = "VAT"
    NONE = "NONE"


class ExtractionSource(StrEnum):
    """How a field value was obtained — critical for audit and confidence."""

    OCR_RULE = "ocr_rule"
    OCR_REGEX = "ocr_regex"
    LAYOUT_MODEL = "layout_model"
    VLM_FALLBACK = "vlm_fallback"
    HUMAN_CORRECTED = "human_corrected"
    LOCAL_VLM = "local_vlm"


class ValidationSeverity(StrEnum):
    """Severity levels for validation flags."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ── Core Value Types ─────────────────────────────────────────────────


class BoundingBox(BaseModel):
    """Normalised bounding box coordinates (0.0 – 1.0 of page dimensions)."""

    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    page: int = Field(default=0, ge=0)


class FieldValue(BaseModel):
    """
    A single extracted field with provenance metadata.
    Every extracted value carries its confidence, source, and optional
    bounding box — this is what enables the dashboard's colour-coded
    confidence overlay and the human-correction audit trail.
    """

    value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    source: ExtractionSource = ExtractionSource.OCR_REGEX
    bounding_box: BoundingBox | None = None


class ValidationFlag(BaseModel):
    """Result of a single validation check."""

    rule: str
    passed: bool
    message: str
    severity: ValidationSeverity
    details: dict = Field(default_factory=dict)


class RiskFlag(BaseModel):
    """An explainable risk contribution persisted against an invoice."""

    code: str
    points: int = Field(ge=0, le=100)
    level: RiskLevel
    message: str
    resolved: bool = False
    details: dict = Field(default_factory=dict)


# ── Invoice Sub-models ───────────────────────────────────────────────


class LineItem(BaseModel):
    """A single line item from the invoice table."""

    description: str = ""
    hsn_sac: str | None = None
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0.00")
    gst_rate: Decimal | None = None
    tax_amount: Decimal = Decimal("0.00")
    discount: Decimal = Decimal("0.00")
    line_total: Decimal = Decimal("0.00")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class VendorDetails(BaseModel):
    """Vendor / supplier information block."""

    name: FieldValue = Field(default_factory=lambda: FieldValue(value=None))
    address: FieldValue | None = None
    gstin: FieldValue | None = None
    pan: FieldValue | None = None
    email: FieldValue | None = None
    phone: FieldValue | None = None
    bank_name: FieldValue | None = None
    bank_account: FieldValue | None = None
    ifsc: FieldValue | None = None


class BuyerDetails(BaseModel):
    """Buyer / customer information block."""

    name: FieldValue | None = None
    address: FieldValue | None = None
    billing_address: FieldValue | None = None
    shipping_address: FieldValue | None = None
    gstin: FieldValue | None = None
    pan: FieldValue | None = None


class TaxDetails(BaseModel):
    """Tax breakdown entry."""

    tax_type: TaxType = TaxType.NONE
    rate_percent: Decimal | None = None
    amount: Decimal = Decimal("0.00")


class QRComparisonResult(BaseModel):
    """Field-level comparison between QR payload data and OCR/rules data."""

    status: Literal["match", "mismatch", "not_comparable"] = "not_comparable"
    ocr_value: str | None = None
    qr_value: str | None = None
    difference: str | None = None
    message: str = "QR/OCR comparison was not possible for this field"


class EInvoiceDetails(BaseModel):
    """Locally detected e-invoice QR metadata; not a government API claim."""

    qr_detected: bool = False
    qr_payload: str | None = None
    irn: str | None = None
    ack_number: str | None = None
    qr_fields: dict[str, str] = Field(default_factory=dict)
    comparison_status: Literal["match", "mismatch", "not_comparable", "not_checked"] = "not_checked"
    comparison_results: dict[str, QRComparisonResult] = Field(default_factory=dict)


# ── Universal invoice data standard ─────────────────────────────────


class StandardInvoiceHeader(BaseModel):
    """The stable, provider-independent invoice header contract."""

    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    po_number: str | None = None
    currency: str = "INR"
    place_of_supply: str | None = None


class StandardParty(BaseModel):
    """A plain-value party block used by exports and downstream systems."""

    name: str | None = None
    address: str | None = None
    gstin: str | None = None
    pan: str | None = None
    email: str | None = None
    phone: str | None = None


class StandardInvoiceItem(BaseModel):
    """A normalized line item with nulls for values that were not evidenced."""

    description: str | None = None
    hsn: str | None = None
    hsn_sac: str | None = None
    quantity: Decimal | None = None
    rate: Decimal | None = None
    unit_price: Decimal | None = None
    gst_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    amount: Decimal | None = None
    discount: Decimal | None = None
    line_total: Decimal | None = None


class StandardTaxSummary(BaseModel):
    """Tax totals in the common Indian invoice vocabulary."""

    cgst: Decimal = Decimal("0.00")
    sgst: Decimal = Decimal("0.00")
    igst: Decimal = Decimal("0.00")
    cess: Decimal = Decimal("0.00")
    other: Decimal = Decimal("0.00")


class StandardTotals(BaseModel):
    subtotal: Decimal | None = None
    discount: Decimal = Decimal("0.00")
    taxable_amount: Decimal | None = None
    tax: Decimal = Decimal("0.00")
    grand_total: Decimal | None = None


class StandardPayment(BaseModel):
    terms: str | None = None
    due_date: str | None = None
    bank_name: str | None = None
    ifsc: str | None = None
    account_number: str | None = None


class StandardEInvoice(BaseModel):
    irn: str | None = None
    ack_number: str | None = None
    qr_detected: bool = False
    qr_payload: str | None = None
    qr_fields: dict[str, str] = Field(default_factory=dict)
    comparison_status: Literal["match", "mismatch", "not_comparable", "not_checked"] = "not_checked"
    comparison_results: dict[str, QRComparisonResult] = Field(default_factory=dict)


class InvoiceDataStandard(BaseModel):
    """
    Universal invoice data standard.

    OCR, layout models, local VLMs, human corrections, AP projections, and
    exports can all use this nested plain-value shape. The richer
    ``InvoiceExtraction`` model remains alongside it so confidence, source,
    and bounding-box provenance are never discarded during review.
    """

    document_type: str = "tax_invoice"
    invoice: StandardInvoiceHeader = Field(default_factory=StandardInvoiceHeader)
    seller: StandardParty = Field(default_factory=StandardParty)
    buyer: StandardParty = Field(default_factory=StandardParty)
    items: list[StandardInvoiceItem] = Field(default_factory=list)
    taxes: StandardTaxSummary = Field(default_factory=StandardTaxSummary)
    totals: StandardTotals = Field(default_factory=StandardTotals)
    payment: StandardPayment = Field(default_factory=StandardPayment)
    einvoice: StandardEInvoice = Field(default_factory=StandardEInvoice)


# Descriptive alias for callers using the terminology from the product brief.
UniversalInvoice = InvoiceDataStandard


# ── Top-Level Extraction Result ──────────────────────────────────────


class InvoiceExtraction(BaseModel):
    """
    Complete extraction result for a single invoice document.
    This is the primary data payload stored in the database and
    returned by the API.
    """

    # Header fields
    document_type: str = "tax_invoice"
    invoice_number: FieldValue = Field(default_factory=lambda: FieldValue(value=None))
    invoice_date: str | None = None
    due_date: str | None = None
    po_reference: FieldValue | None = None
    payment_terms: str | None = None
    place_of_supply: str | None = None

    # Parties
    vendor: VendorDetails = Field(default_factory=VendorDetails)
    buyer: BuyerDetails | None = None

    # Line items & financials
    line_items: list[LineItem] = Field(default_factory=list)
    taxes: list[TaxDetails] = Field(default_factory=list)
    subtotal: Decimal | None = None
    discount_total: Decimal = Decimal("0.00")
    tax_total: Decimal = Decimal("0.00")
    shipping_amount: Decimal = Decimal("0.00")
    grand_total: Decimal | None = None
    currency: str = "INR"
    einvoice: EInvoiceDetails = Field(default_factory=EInvoiceDetails)

    # Quality metadata
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    validation_flags: list[ValidationFlag] = Field(default_factory=list)
    extraction_source: ExtractionSource = ExtractionSource.OCR_REGEX
    # AI can locate scalar values even when OCR did not produce a word box.
    field_locations: dict[str, BoundingBox] = Field(default_factory=dict)
    # Bounded raw structure from Docling/PP-StructureV3 for audit and future
    # re-parsing; normalized AP fields remain the stable contract.
    document_structure: dict[str, Any] | None = None
    processing_time_ms: int = 0
    vlm_input_tokens: int = 0
    vlm_output_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0.00")

    # Canonical provider-neutral payload. It is populated at the projection
    # boundary and remains optional so old extraction JSON stays compatible.
    standardized_invoice: InvoiceDataStandard | None = None

    @staticmethod
    def _field_text(field: FieldValue | None) -> str | None:
        if field is None or field.value in (None, ""):
            return None
        return field.value

    @staticmethod
    def _known_amount(value: Decimal, confidence: float) -> Decimal | None:
        # Existing line-item extractors use zero as their compatibility
        # default. Do not expose that default as an asserted value when the
        # line has no extraction confidence.
        if value == 0 and confidence <= 0:
            return None
        return value

    def to_standard(self) -> InvoiceDataStandard:
        """Convert provenance-rich extraction into the universal plain shape."""

        taxes = StandardTaxSummary()
        for tax in self.taxes:
            amount = tax.amount
            if tax.tax_type == TaxType.IGST:
                taxes.igst += amount
            elif tax.tax_type == TaxType.CGST_SGST:
                taxes.cgst += amount / 2
                taxes.sgst += amount - (amount / 2)
            elif tax.tax_type == TaxType.CGST:
                taxes.cgst += amount
            elif tax.tax_type == TaxType.SGST:
                taxes.sgst += amount
            elif tax.tax_type == TaxType.CESS:
                taxes.cess += amount
            elif tax.tax_type in {TaxType.GST, TaxType.VAT}:
                taxes.other += amount

        seller = StandardParty(
            name=self._field_text(self.vendor.name),
            address=self._field_text(self.vendor.address),
            gstin=self._field_text(self.vendor.gstin),
            pan=self._field_text(self.vendor.pan),
            email=self._field_text(self.vendor.email),
            phone=self._field_text(self.vendor.phone),
        )
        buyer = StandardParty(
            name=self._field_text(self.buyer.name) if self.buyer else None,
            address=(
                (
                    self._field_text(self.buyer.address)
                    or self._field_text(self.buyer.billing_address)
                )
                if self.buyer
                else None
            ),
            gstin=self._field_text(self.buyer.gstin) if self.buyer else None,
            pan=self._field_text(self.buyer.pan) if self.buyer else None,
        )
        return InvoiceDataStandard(
            document_type=self.document_type,
            invoice=StandardInvoiceHeader(
                invoice_number=self._field_text(self.invoice_number),
                invoice_date=self.invoice_date,
                due_date=self.due_date,
                po_number=self._field_text(self.po_reference),
                currency=self.currency or "INR",
                place_of_supply=self.place_of_supply,
            ),
            seller=seller,
            buyer=buyer,
            items=[
                StandardInvoiceItem(
                    description=item.description or None,
                    hsn=item.hsn_sac,
                    hsn_sac=item.hsn_sac,
                    quantity=self._known_amount(item.quantity, item.confidence),
                    rate=self._known_amount(item.unit_price, item.confidence),
                    unit_price=self._known_amount(item.unit_price, item.confidence),
                    gst_rate=item.gst_rate,
                    tax_amount=self._known_amount(item.tax_amount, item.confidence),
                    amount=self._known_amount(item.line_total, item.confidence),
                    discount=self._known_amount(item.discount, item.confidence),
                    line_total=self._known_amount(item.line_total, item.confidence),
                )
                for item in self.line_items
            ],
            taxes=taxes,
            totals=StandardTotals(
                subtotal=self.subtotal,
                discount=self.discount_total,
                taxable_amount=(
                    self.subtotal - self.discount_total if self.subtotal is not None else None
                ),
                tax=self.tax_total,
                grand_total=self.grand_total,
            ),
            payment=StandardPayment(
                terms=self.payment_terms,
                due_date=self.due_date,
                bank_name=self._field_text(self.vendor.bank_name),
                ifsc=self._field_text(self.vendor.ifsc),
                account_number=self._field_text(self.vendor.bank_account),
            ),
            einvoice=StandardEInvoice(
                irn=self.einvoice.irn,
                ack_number=self.einvoice.ack_number,
                qr_detected=self.einvoice.qr_detected,
                qr_payload=self.einvoice.qr_payload,
                qr_fields=self.einvoice.qr_fields,
                comparison_status=self.einvoice.comparison_status,
                comparison_results=self.einvoice.comparison_results,
            ),
        )

    def ensure_standardized(self) -> "InvoiceExtraction":
        """Refresh and attach the canonical payload after any correction."""

        self.standardized_invoice = self.to_standard()
        return self


# ── API Request / Response Models ────────────────────────────────────


class DocumentUploadResponse(BaseModel):
    """Returned immediately on upload (HTTP 202)."""

    document_id: str
    status: DocumentStatus
    message: str = "Document queued for processing"
    duplicate_of: str | None = None


class BatchUploadResponse(BaseModel):
    documents: list[DocumentUploadResponse]
    accepted: int
    rejected: int = 0


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class DocumentResponse(BaseModel):
    """Full document status + extraction result."""

    id: str
    filename: str
    status: DocumentStatus
    file_size_bytes: int | None = None
    page_count: int = 1
    extraction: InvoiceExtraction | None = None
    standardized_invoice: InvoiceDataStandard | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    processing_time_ms: int | None = None
    file_url: str | None = None
    preview_url: str | None = None


class PreprocessingArtifactResponse(BaseModel):
    """Persisted original/processed page evidence and transformation metadata."""

    id: str
    document_id: str
    page: int
    original_width: int
    original_height: int
    processed_width: int
    processed_height: int
    steps_applied: list[str] = Field(default_factory=list)
    deskew_angle: float = 0.0
    orientation_correction: int = 0
    estimated_dpi: int | None = None
    processed_preview_url: str | None = None


class DocumentListResponse(BaseModel):
    """Paginated document list."""

    documents: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class OCRTokenResponse(BaseModel):
    id: str
    document_id: str
    page: int
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int
    page_width: int
    page_height: int

    @computed_field
    @property
    def bbox(self) -> list[int]:
        """Compatibility-friendly token rectangle: [x0, y0, x1, y1]."""

        return [self.x, self.y, self.x + self.width, self.y + self.height]


class FieldCorrectionRequest(BaseModel):
    """Human correction of an extracted field."""

    field_path: str  # e.g. "invoice_number.value", "vendor.name.value"
    old_value: str | None = None
    new_value: str
    corrected_by: str = "user"


class AuditEntry(BaseModel):
    """Record of a single field correction."""

    id: str
    document_id: str
    field_path: str
    old_value: str | None
    new_value: str
    corrected_by: str
    timestamp: datetime
    # Explicit training-data aliases.  ``old_value``/``new_value`` remain in
    # the contract for compatibility with the original audit endpoint.
    predicted: str | None = None
    correct: str | None = None


class AnalyticsSummary(BaseModel):
    """High-level platform metrics."""

    total_documents: int = 0
    completed_documents: int = 0
    failed_documents: int = 0
    average_confidence: float = 0.0
    average_processing_time_ms: float = 0.0
    vlm_fallback_rate: float = 0.0
    documents_today: int = 0
    documents_this_week: int = 0
    average_cost_usd: float = 0.0


class VendorAnalytics(BaseModel):
    """Per-vendor spend analytics."""

    vendor_name: str
    document_count: int
    total_spend: Decimal = Decimal("0.00")
    average_confidence: float = 0.0
    currency: str = "INR"


class AnalyticsVendorsResponse(BaseModel):
    """Vendor-level analytics."""

    vendors: list[VendorAnalytics]


class VolumePoint(BaseModel):
    date: str
    document_count: int
    average_confidence: float = 0.0
    average_processing_time_ms: float = 0.0


class AnalyticsTrendsResponse(BaseModel):
    points: list[VolumePoint]


# ── Accounts-payable contracts ──────────────────────────────────────


class VendorResponse(BaseModel):
    id: str
    name: str
    gstin: str | None = None
    pan: str | None = None
    address: str | None = None
    state: str | None = None
    email: str | None = None
    phone: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    ifsc: str | None = None
    payment_terms: str | None = None
    invoice_count: int = 0
    total_spend: Decimal = Decimal("0.00")
    outstanding: Decimal = Decimal("0.00")
    created_at: datetime | None = None


class VendorCreateRequest(BaseModel):
    name: str
    gstin: str | None = None
    pan: str | None = None
    address: str | None = None
    state: str | None = None
    email: str | None = None
    phone: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    ifsc: str | None = None
    payment_terms: str | None = None


class InvoiceItemResponse(BaseModel):
    id: str
    description: str
    sku: str | None = None
    hsn: str | None = None
    sac: str | None = None
    hsn_sac: str | None = None
    quantity: Decimal = Decimal("0")
    unit: str | None = None
    unit_price: Decimal = Decimal("0.00")
    rate: Decimal = Decimal("0.00")
    discount: Decimal = Decimal("0.00")
    taxable_value: Decimal = Decimal("0.00")
    gst_rate: Decimal | None = None
    tax_amount: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    line_total: Decimal = Decimal("0.00")
    confidence: float = 0.0


class InvoiceTaxResponse(BaseModel):
    id: str
    tax_type: str
    rate_percent: Decimal | None = None
    amount: Decimal = Decimal("0.00")


class ValidationResultResponse(BaseModel):
    id: str
    rule: str
    passed: bool
    severity: ValidationSeverity
    message: str
    details: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class RiskFlagResponse(BaseModel):
    id: str
    code: str
    points: int
    level: RiskLevel
    message: str
    resolved: bool = False
    details: dict = Field(default_factory=dict)
    created_at: datetime | None = None


class PaymentResponse(BaseModel):
    id: str
    invoice_id: str
    amount: Decimal
    payment_date: str
    method: str = "bank_transfer"
    reference: str | None = None
    status: PaymentStatus = PaymentStatus.CONFIRMED
    notes: str | None = None
    created_at: datetime | None = None


class WorkflowEventResponse(BaseModel):
    id: str
    invoice_id: str
    action: str
    from_status: InvoiceStatus | None = None
    to_status: InvoiceStatus
    actor: str
    comment: str | None = None
    created_at: datetime | None = None


class PurchaseOrderItemCreate(BaseModel):
    description: str
    hsn_sac: str | None = None
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0.00")
    tax_rate: Decimal | None = None
    line_total: Decimal | None = None


class PurchaseOrderCreateRequest(BaseModel):
    number: str
    vendor_id: str | None = None
    vendor_name: str | None = None
    order_date: str | None = None
    expected_delivery: str | None = None
    currency: str = "INR"
    tax_total: Decimal = Field(default=Decimal("0.00"), ge=0)
    notes: str | None = None
    items: list[PurchaseOrderItemCreate] = Field(default_factory=list)


class PurchaseOrderItemResponse(PurchaseOrderItemCreate):
    id: str
    line_total: Decimal = Decimal("0.00")


class GoodsReceiptItemCreate(BaseModel):
    purchase_order_item_id: str
    quantity_received: Decimal = Field(default=Decimal("0"), ge=0)


class GoodsReceiptCreateRequest(BaseModel):
    purchase_order_id: str
    receipt_number: str
    receipt_date: str
    notes: str | None = None
    items: list[GoodsReceiptItemCreate] = Field(default_factory=list)


class GoodsReceiptResponse(GoodsReceiptCreateRequest):
    id: str
    status: str = "received"
    created_at: datetime | None = None


class PurchaseOrderResponse(BaseModel):
    id: str
    number: str
    vendor: VendorResponse | None = None
    vendor_id: str | None = None
    status: str = "open"
    order_date: str | None = None
    expected_delivery: str | None = None
    currency: str = "INR"
    subtotal: Decimal = Decimal("0.00")
    tax_total: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    notes: str | None = None
    items: list[PurchaseOrderItemResponse] = Field(default_factory=list)
    receipts: list[GoodsReceiptResponse] = Field(default_factory=list)
    created_at: datetime | None = None


class InvoiceActionRequest(BaseModel):
    action: WorkflowAction
    comment: str | None = None
    override: bool = False
    actor: str = "local_user"


class InvoiceQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class InvoiceQuestionResponse(BaseModel):
    question: str
    answer: str
    evidence: list[str] = Field(default_factory=list)
    provider: str = "deterministic-rules"
    grounded: bool = True


class PaymentCreateRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_date: str
    method: str = "bank_transfer"
    reference: str | None = None
    notes: str | None = None
    actor: str = "local_user"


class InvoiceFieldUpdateRequest(BaseModel):
    field_path: str
    new_value: str
    old_value: str | None = None
    corrected_by: str = "local_user"


class InvoiceResponse(BaseModel):
    id: str
    document_id: str
    filename: str | None = None
    preview_url: str | None = None
    page_count: int = 1
    # Document processing is intentionally separate from AP workflow status:
    # pending/preprocessing/ocr/extracting/validating -> completed, then the
    # projected invoice enters review_required/approved/payment/paid.
    processing_status: DocumentStatus | None = None
    status: InvoiceStatus
    review_reason: str | None = None
    invoice_number: str | None = None
    duplicate_fingerprint: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    po_number: str | None = None
    currency: str = "INR"
    subtotal: Decimal | None = None
    discount_total: Decimal = Decimal("0.00")
    taxable_amount: Decimal | None = None
    tax_total: Decimal = Decimal("0.00")
    cgst: Decimal = Decimal("0.00")
    sgst: Decimal = Decimal("0.00")
    igst: Decimal = Decimal("0.00")
    grand_total: Decimal | None = None
    outstanding_amount: Decimal = Decimal("0.00")
    overall_confidence: float = 0.0
    confidence_score: float = 0.0
    ocr_text: str | None = None
    risk_score: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    match_status: MatchStatus = MatchStatus.NOT_APPLICABLE
    match_details: dict = Field(default_factory=dict)
    vendor: VendorResponse | None = None
    extraction: InvoiceExtraction | None = None
    standardized_invoice: InvoiceDataStandard | None = None
    items: list[InvoiceItemResponse] = Field(default_factory=list)
    taxes: list[InvoiceTaxResponse] = Field(default_factory=list)
    validations: list[ValidationResultResponse] = Field(default_factory=list)
    risk_flags: list[RiskFlagResponse] = Field(default_factory=list)
    payments: list[PaymentResponse] = Field(default_factory=list)
    workflow: list[WorkflowEventResponse] = Field(default_factory=list)
    corrections: list[AuditEntry] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VendorInvoiceSummary(BaseModel):
    id: str
    invoice_number: str | None = None
    invoice_date: str | None = None
    grand_total: Decimal | None = None
    outstanding_amount: Decimal = Decimal("0.00")
    status: InvoiceStatus


class VendorDetailResponse(VendorResponse):
    invoices: list[VendorInvoiceSummary] = Field(default_factory=list)


class InvoiceListResponse(BaseModel):
    invoices: list[InvoiceResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class AgingBucket(BaseModel):
    label: str
    amount: Decimal = Decimal("0.00")
    count: int = 0


class APDashboardSummary(BaseModel):
    total_invoices: int = 0
    processing_invoices: int = 0
    review_invoices: int = 0
    approved_invoices: int = 0
    awaiting_payment_invoices: int = 0
    paid_invoices: int = 0
    rejected_invoices: int = 0
    duplicate_invoices: int = 0
    on_hold_invoices: int = 0
    outstanding_total: Decimal = Decimal("0.00")
    due_this_week: Decimal = Decimal("0.00")
    overdue_total: Decimal = Decimal("0.00")
    high_risk_count: int = 0
    average_confidence: float = 0.0
    total_tax: Decimal = Decimal("0.00")
    aging: list[AgingBucket] = Field(default_factory=list)


class APAnalyticsResponse(BaseModel):
    summary: APDashboardSummary
    vendors: list[VendorAnalytics] = Field(default_factory=list)
    trends: list[VolumePoint] = Field(default_factory=list)


class PaymentDueResponse(BaseModel):
    invoice_id: str
    invoice_number: str | None = None
    vendor: str | None = None
    due_date: str | None = None
    grand_total: Decimal | None = None
    outstanding_amount: Decimal = Decimal("0.00")
    status: InvoiceStatus
    overdue: bool = False


class ProviderStatusResponse(BaseModel):
    profile: str
    ocr_engine: str
    layout_engine: str = "spatial-rules"
    document_parser: str = "pymupdf"
    configured_provider: str
    active_provider: str
    available: bool
    deterministic_fallback: bool = True
    zero_cost_default: bool = True
    message: str


class GSTSummaryResponse(BaseModel):
    total_tax: Decimal = Decimal("0.00")
    invoice_count: int = 0
    by_type: dict[str, Decimal] = Field(default_factory=dict)


class ImportResult(BaseModel):
    accepted: int
    rejected: int
    errors: list[str] = Field(default_factory=list)
