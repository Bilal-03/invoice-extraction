"""Add the normalized accounts-payable domain."""

import sqlalchemy as sa

from alembic import op

revision = "20260815_02"
down_revision = "20260730_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("gstin", sa.String(15)),
        sa.Column("pan", sa.String(10)),
        sa.Column("address", sa.Text()),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(40)),
        sa.Column("bank_name", sa.String(255)),
        sa.Column("bank_account", sa.String(100)),
        sa.Column("ifsc", sa.String(20)),
        sa.Column("payment_terms", sa.String(100)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "gstin", name="uq_vendors_tenant_gstin"),
    )
    op.create_index("ix_vendors_tenant", "vendors", ["tenant_id"])
    op.create_index("ix_vendors_tenant_name", "vendors", ["tenant_id", "normalized_name"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("vendor_id", sa.String(36), sa.ForeignKey("vendors.id")),
        sa.Column("invoice_number", sa.String(120)),
        sa.Column("normalized_invoice_number", sa.String(120)),
        sa.Column("invoice_date", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("po_number", sa.String(120)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="INR"),
        sa.Column("subtotal", sa.Numeric(18, 2)),
        sa.Column("discount_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("taxable_amount", sa.Numeric(18, 2)),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(18, 2)),
        sa.Column("outstanding_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="review_required"),
        sa.Column("review_reason", sa.Text()),
        sa.Column("overall_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column("match_status", sa.String(30), nullable=False, server_default="not_applicable"),
        sa.Column("match_details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "document_id", name="uq_invoices_tenant_document"),
    )
    op.create_index("ix_invoices_tenant", "invoices", ["tenant_id"])
    op.create_index("ix_invoices_tenant_status", "invoices", ["tenant_id", "status"])
    op.create_index(
        "ix_invoices_tenant_number", "invoices", ["tenant_id", "normalized_invoice_number"]
    )

    op.create_table(
        "invoice_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("hsn_sac", sa.String(50)),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(30)),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("taxable_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("gst_rate", sa.Numeric(8, 3)),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_invoice_items_invoice", "invoice_items", ["invoice_id"])

    op.create_table(
        "invoice_taxes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("tax_type", sa.String(30), nullable=False),
        sa.Column("rate_percent", sa.Numeric(8, 3)),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_invoice_taxes_invoice", "invoice_taxes", ["invoice_id"])

    op.create_table(
        "invoice_validations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("rule", sa.String(80), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoice_validations_invoice", "invoice_validations", ["invoice_id"])

    op.create_table(
        "invoice_risk_flags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoice_risk_flags_invoice", "invoice_risk_flags", ["invoice_id"])

    op.create_table(
        "workflow_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("from_status", sa.String(30)),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False, server_default="local_user"),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_events_invoice", "workflow_events", ["invoice_id"])

    op.create_table(
        "ai_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id")),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120)),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Numeric(12, 8), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_runs_document", "ai_runs", ["document_id"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("number", sa.String(120), nullable=False),
        sa.Column("vendor_id", sa.String(36), sa.ForeignKey("vendors.id")),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("order_date", sa.Date()),
        sa.Column("expected_delivery", sa.Date()),
        sa.Column("currency", sa.String(10), nullable=False, server_default="INR"),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "number", name="uq_purchase_orders_tenant_number"),
    )
    op.create_index("ix_purchase_orders_tenant", "purchase_orders", ["tenant_id"])
    op.create_index("ix_purchase_orders_tenant_status", "purchase_orders", ["tenant_id", "status"])

    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "purchase_order_id", sa.String(36), sa.ForeignKey("purchase_orders.id"), nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("hsn_sac", sa.String(50)),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_rate", sa.Numeric(8, 3)),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_purchase_order_items_po", "purchase_order_items", ["purchase_order_id"])

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column(
            "purchase_order_id", sa.String(36), sa.ForeignKey("purchase_orders.id"), nullable=False
        ),
        sa.Column("receipt_number", sa.String(120), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_goods_receipts_po", "goods_receipts", ["purchase_order_id"])

    op.create_table(
        "goods_receipt_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "goods_receipt_id", sa.String(36), sa.ForeignKey("goods_receipts.id"), nullable=False
        ),
        sa.Column(
            "purchase_order_item_id",
            sa.String(36),
            sa.ForeignKey("purchase_order_items.id"),
            nullable=False,
        ),
        sa.Column("quantity_received", sa.Numeric(18, 4), nullable=False, server_default="0"),
    )
    op.create_index("ix_goods_receipt_items_receipt", "goods_receipt_items", ["goods_receipt_id"])

    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, server_default="local"),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("method", sa.String(50), nullable=False, server_default="bank_transfer"),
        sa.Column("reference", sa.String(120)),
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payments_invoice", "payments", ["invoice_id"])


def downgrade() -> None:
    for table in (
        "payments",
        "goods_receipt_items",
        "goods_receipts",
        "purchase_order_items",
        "purchase_orders",
        "ai_runs",
        "workflow_events",
        "invoice_risk_flags",
        "invoice_validations",
        "invoice_taxes",
        "invoice_items",
        "invoices",
        "vendors",
    ):
        op.drop_table(table)
