"""Supabase foundation: durable jobs, event history, and tenant ownership."""

from alembic import op
import sqlalchemy as sa

revision = "20260730_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.Integer()),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text()),
        sa.Column("extraction_result", sa.JSON()),
        sa.Column("overall_confidence", sa.Float()),
        sa.Column("processing_time_ms", sa.Integer()),
        sa.Column("extraction_source", sa.String(20)),
        sa.Column("vendor_name", sa.String(255)),
        sa.Column("grand_total", sa.Float()),
        sa.Column("currency", sa.String(10), server_default="INR"),
        sa.Column("document_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (("ix_documents_tenant_created", ["tenant_id", "created_at"]), ("ix_documents_hash", ["document_hash"]), ("ix_documents_status", ["status"])):
        op.create_index(name, "documents", columns)
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("field_path", sa.String(100), nullable=False),
        sa.Column("old_value", sa.Text()), sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("corrected_by", sa.String(100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_entries_document", "audit_entries", ["document_id"])
    op.create_table(
        "document_jobs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"), sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"), sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)), sa.Column("locked_by", sa.String(100)), sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_document_jobs_claim", "document_jobs", ["status", "available_at"])
    op.create_table(
        "document_events",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"), sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("stage", sa.String(40)), sa.Column("message", sa.Text()),
        sa.Column("metadata_json", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_events_document_created", "document_events", ["document_id", "created_at"])


def downgrade() -> None:
    for table in ("document_events", "document_jobs", "audit_entries", "documents"):
        op.drop_table(table)
