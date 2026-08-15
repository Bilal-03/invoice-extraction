"""Add deterministic invoice duplicate fingerprints."""

import sqlalchemy as sa

from alembic import op


revision = "20260816_05"
down_revision = "20260816_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("duplicate_fingerprint", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_invoices_tenant_duplicate_fingerprint",
        "invoices",
        ["tenant_id", "duplicate_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_tenant_duplicate_fingerprint", table_name="invoices")
    op.drop_column("invoices", "duplicate_fingerprint")
