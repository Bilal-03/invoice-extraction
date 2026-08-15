"""Persist original/processed page evidence for OCR review."""

import sqlalchemy as sa

from alembic import op


revision = "20260816_04"
down_revision = "20260815_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_preprocessing_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("page", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("original_file_path", sa.String(500), nullable=False),
        sa.Column("processed_file_path", sa.String(500), nullable=False),
        sa.Column("original_width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("original_height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("steps_applied", sa.JSON(), nullable=False),
        sa.Column("deskew_angle", sa.Float(), nullable=False, server_default="0"),
        sa.Column("orientation_correction", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_dpi", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "page", name="uq_preprocessing_document_page"),
    )
    op.create_index(
        "ix_preprocessing_artifacts_document",
        "document_preprocessing_artifacts",
        ["document_id"],
    )
    op.create_index(
        "ix_preprocessing_artifacts_tenant",
        "document_preprocessing_artifacts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_preprocessing_artifacts_document_page",
        "document_preprocessing_artifacts",
        ["document_id", "page"],
    )


def downgrade() -> None:
    op.drop_table("document_preprocessing_artifacts")
