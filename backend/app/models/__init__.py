"""Public ORM model boundary.

The project keeps the mapped classes in ``app.domain.entities`` because the
domain module is also used by the worker and migrations.  This package is the
stable import surface for API/service code that wants the conventional
``app.models`` layout without duplicating SQLAlchemy mappings.
"""

from app.core.database import Base
from app.domain.entities import (
    AIRun,
    AuditEntryModel,
    AuditLog,
    Document,
    DocumentEvent,
    DocumentJob,
    DocumentPreprocessingArtifact,
    GoodsReceipt,
    GoodsReceiptItem,
    HumanCorrection,
    Invoice,
    InvoiceFlag,
    InvoiceItem,
    InvoiceRiskFlag,
    InvoiceTax,
    InvoiceValidation,
    OCRToken,
    Payment,
    PurchaseOrder,
    PurchaseOrderItem,
    User,
    Vendor,
    WorkflowEvent,
)

__all__ = [
    "AIRun",
    "AuditEntryModel",
    "AuditLog",
    "Base",
    "Document",
    "DocumentEvent",
    "DocumentJob",
    "DocumentPreprocessingArtifact",
    "GoodsReceipt",
    "GoodsReceiptItem",
    "HumanCorrection",
    "Invoice",
    "InvoiceFlag",
    "InvoiceItem",
    "InvoiceRiskFlag",
    "InvoiceTax",
    "InvoiceValidation",
    "OCRToken",
    "Payment",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "User",
    "Vendor",
    "WorkflowEvent",
]
