"""
Pydantic v2 schemas — the single source of truth for data shapes.

These models serve triple duty:
  1. API request/response contracts (FastAPI auto-generates OpenAPI from these)
  2. Database serialisation boundary (stored as JSON in the extraction_result column)
  3. Frontend TypeScript types (generated from the OpenAPI spec)
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

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


class TaxType(StrEnum):
    """Supported tax classification types."""

    GST = "GST"
    CGST_SGST = "CGST_SGST"
    IGST = "IGST"
    VAT = "VAT"
    NONE = "NONE"


class ExtractionSource(StrEnum):
    """How a field value was obtained — critical for audit and confidence."""

    OCR_REGEX = "ocr_regex"
    LAYOUT_MODEL = "layout_model"
    VLM_FALLBACK = "vlm_fallback"
    HUMAN_CORRECTED = "human_corrected"


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


# ── Invoice Sub-models ───────────────────────────────────────────────


class LineItem(BaseModel):
    """A single line item from the invoice table."""

    description: str = ""
    quantity: Decimal = Decimal("0")
    unit_price: Decimal = Decimal("0.00")
    discount: Decimal = Decimal("0.00")
    line_total: Decimal = Decimal("0.00")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class VendorDetails(BaseModel):
    """Vendor / supplier information block."""

    name: FieldValue = Field(default_factory=lambda: FieldValue(value=None))
    address: FieldValue | None = None
    gstin: FieldValue | None = None
    bank_account: FieldValue | None = None


class BuyerDetails(BaseModel):
    """Buyer / customer information block."""

    name: FieldValue | None = None
    billing_address: FieldValue | None = None
    shipping_address: FieldValue | None = None


class TaxDetails(BaseModel):
    """Tax breakdown entry."""

    tax_type: TaxType = TaxType.NONE
    rate_percent: Decimal | None = None
    amount: Decimal = Decimal("0.00")


# ── Top-Level Extraction Result ──────────────────────────────────────


class InvoiceExtraction(BaseModel):
    """
    Complete extraction result for a single invoice document.
    This is the primary data payload stored in the database and
    returned by the API.
    """

    # Header fields
    invoice_number: FieldValue = Field(default_factory=lambda: FieldValue(value=None))
    invoice_date: str | None = None
    due_date: str | None = None
    po_reference: FieldValue | None = None
    payment_terms: str | None = None

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

    # Quality metadata
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    validation_flags: list[ValidationFlag] = Field(default_factory=list)
    extraction_source: ExtractionSource = ExtractionSource.OCR_REGEX
    # AI can locate scalar values even when OCR did not produce a word box.
    field_locations: dict[str, BoundingBox] = Field(default_factory=dict)
    processing_time_ms: int = 0
    vlm_input_tokens: int = 0
    vlm_output_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0.00")


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
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    processing_time_ms: int | None = None
    file_url: str | None = None
    preview_url: str | None = None


class DocumentListResponse(BaseModel):
    """Paginated document list."""

    documents: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


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
