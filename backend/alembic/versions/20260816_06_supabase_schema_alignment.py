"""Align the AP schema with the Supabase relational design.

The first AP migration used implementation-oriented names for a few tables.
This migration keeps the data and foreign keys intact while moving them to the
public contract names used by the product: invoice_flags, ai_extractions,
human_corrections, and audit_logs.
"""

import sqlalchemy as sa

from alembic import op


revision = "20260816_06"
down_revision = "20260816_05"
branch_labels = None
depends_on = None


def _rename_index(old: str, new: str) -> None:
    op.execute(sa.text(f'ALTER INDEX "{old}" RENAME TO "{new}"'))


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(40), nullable=False, server_default="ap_user"),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant", "users", ["tenant_id"])
    op.create_index("ix_users_tenant_active", "users", ["tenant_id", "is_active"])

    # Preserve all existing data while matching the public table contract.
    op.rename_table("audit_entries", "human_corrections")
    _rename_index("ix_audit_entries_document", "ix_human_corrections_document")
    op.rename_table("invoice_risk_flags", "invoice_flags")
    _rename_index("ix_invoice_risk_flags_invoice", "ix_invoice_flags_invoice")
    op.rename_table("ai_runs", "ai_extractions")
    _rename_index("ix_ai_runs_document", "ix_ai_extractions_document")
    op.rename_table("workflow_events", "audit_logs")
    _rename_index("ix_workflow_events_invoice", "ix_audit_logs_invoice")

    op.add_column("documents", sa.Column("ocr_text", sa.Text(), nullable=True))
    op.add_column("vendors", sa.Column("state", sa.String(120), nullable=True))

    for name in ("cgst", "sgst", "igst"):
        op.add_column(
            "invoices",
            sa.Column(
                name,
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
        )
    op.add_column(
        "invoices",
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("invoices", sa.Column("ocr_text", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE invoices
            SET confidence_score = COALESCE(overall_confidence, 0),
                cgst = COALESCE((
                    SELECT SUM(
                        CASE WHEN tax_type = 'CGST_SGST' THEN amount / 2 ELSE amount END
                    )
                    FROM invoice_taxes
                    WHERE invoice_taxes.invoice_id = invoices.id
                      AND tax_type IN ('CGST', 'CGST_SGST')
                ), 0),
                sgst = COALESCE((
                    SELECT SUM(
                        CASE WHEN tax_type = 'CGST_SGST' THEN amount - (amount / 2) ELSE amount END
                    )
                    FROM invoice_taxes
                    WHERE invoice_taxes.invoice_id = invoices.id
                      AND tax_type IN ('SGST', 'CGST_SGST')
                ), 0),
                igst = COALESCE((
                    SELECT SUM(amount)
                    FROM invoice_taxes
                    WHERE invoice_taxes.invoice_id = invoices.id
                      AND tax_type = 'IGST'
                ), 0)
            """
        )
    )

    for name, source in (("rate", "unit_price"), ("tax", "tax_amount")):
        op.add_column(
            "invoice_items",
            sa.Column(name, sa.Numeric(18, 2), nullable=False, server_default="0"),
        )
        op.execute(
            sa.text(f"UPDATE invoice_items SET {name} = COALESCE({source}, 0)")
        )
    op.add_column("invoice_items", sa.Column("sku", sa.String(120), nullable=True))
    op.add_column("invoice_items", sa.Column("hsn", sa.String(50), nullable=True))
    op.add_column("invoice_items", sa.Column("sac", sa.String(50), nullable=True))
    op.execute(sa.text("UPDATE invoice_items SET hsn = hsn_sac WHERE hsn_sac IS NOT NULL"))


def downgrade() -> None:
    op.drop_column("invoice_items", "sac")
    op.drop_column("invoice_items", "hsn")
    op.drop_column("invoice_items", "sku")
    op.drop_column("invoice_items", "tax")
    op.drop_column("invoice_items", "rate")
    op.drop_column("invoices", "ocr_text")
    op.drop_column("invoices", "confidence_score")
    op.drop_column("invoices", "igst")
    op.drop_column("invoices", "sgst")
    op.drop_column("invoices", "cgst")
    op.drop_column("vendors", "state")
    op.drop_column("documents", "ocr_text")

    op.rename_table("audit_logs", "workflow_events")
    _rename_index("ix_audit_logs_invoice", "ix_workflow_events_invoice")
    op.rename_table("ai_extractions", "ai_runs")
    _rename_index("ix_ai_extractions_document", "ix_ai_runs_document")
    op.rename_table("invoice_flags", "invoice_risk_flags")
    _rename_index("ix_invoice_flags_invoice", "ix_invoice_risk_flags_invoice")
    op.rename_table("human_corrections", "audit_entries")
    _rename_index("ix_human_corrections_document", "ix_audit_entries_document")

    op.drop_index("ix_users_tenant_active", table_name="users")
    op.drop_index("ix_users_tenant", table_name="users")
    op.drop_table("users")
