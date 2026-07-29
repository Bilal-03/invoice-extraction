"""
SQLAlchemy ORM entities — database table definitions.

These map 1:1 to database tables. The extraction result is stored as
a JSON column, keeping the relational structure for queryable metadata
while using JSON flexibility for the semi-structured extraction payload.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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

    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    field_path: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_by: Mapped[str] = mapped_column(String(100), default="user")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
