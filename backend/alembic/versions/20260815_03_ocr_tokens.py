"""Persist word-level OCR evidence."""

import sqlalchemy as sa

from alembic import op

revision = "20260815_03"
down_revision = "20260815_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("page", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("x", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("y", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ocr_tokens_document", "ocr_tokens", ["document_id"])
    op.create_index("ix_ocr_tokens_tenant", "ocr_tokens", ["tenant_id"])
    op.create_index("ix_ocr_tokens_document_page", "ocr_tokens", ["document_id", "page"])


def downgrade() -> None:
    op.drop_table("ocr_tokens")
