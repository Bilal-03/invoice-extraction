"""Grounded invoice Q&A with a local-model path and deterministic fallback."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.adapters.vlm.base import VLMClient
from app.core.logging import get_logger
from app.domain.schemas import InvoiceExtraction, InvoiceQuestionResponse

logger = get_logger(__name__)


def build_invoice_context(bundle: dict[str, Any]) -> dict[str, Any]:
    """Convert the AP bundle into JSON-safe context for the local assistant."""

    invoice = bundle["invoice"]
    vendor = bundle.get("vendor")
    document = bundle.get("document")
    extraction = (
        InvoiceExtraction.model_validate(document.extraction_result)
        if document is not None and document.extraction_result
        else None
    )
    extraction_json = (
        extraction.model_dump(
            mode="json",
            exclude={"document_structure", "field_locations"},
        )
        if extraction
        else None
    )
    return {
        "invoice": {
            "id": _get(invoice, "id"),
            "invoice_number": _get(invoice, "invoice_number"),
            "invoice_date": _date_text(_get(invoice, "invoice_date")),
            "due_date": _date_text(_get(invoice, "due_date")),
            "po_number": _get(invoice, "po_number"),
            "currency": _get(invoice, "currency", "INR"),
            "subtotal": _decimal_text(_get(invoice, "subtotal")),
            "tax_total": _decimal_text(_get(invoice, "tax_total")),
            "grand_total": _decimal_text(_get(invoice, "grand_total")),
            "outstanding_amount": _decimal_text(_get(invoice, "outstanding_amount")),
            "status": _get(invoice, "status"),
            "risk_score": _get(invoice, "risk_score", 0),
            "risk_level": _get(invoice, "risk_level"),
            "match_status": _get(invoice, "match_status"),
            "match_details": _get(invoice, "match_details", {}) or {},
        },
        "vendor": (
            {
                "name": _get(vendor, "name"),
                "gstin": _get(vendor, "gstin"),
                "pan": _get(vendor, "pan"),
                "address": _get(vendor, "address"),
                "payment_terms": _get(vendor, "payment_terms"),
            }
            if vendor
            else None
        ),
        "items": [
            {
                "description": _get(item, "description", ""),
                "hsn_sac": _get(item, "hsn_sac"),
                "quantity": _decimal_text(_get(item, "quantity")),
                "unit_price": _decimal_text(_get(item, "unit_price")),
                "gst_rate": _decimal_text(_get(item, "gst_rate")),
                "tax_amount": _decimal_text(_get(item, "tax_amount")),
                "line_total": _decimal_text(_get(item, "line_total")),
            }
            for item in bundle.get("items", [])
        ],
        "taxes": [
            {
                "tax_type": _get(tax, "tax_type", ""),
                "rate_percent": _decimal_text(_get(tax, "rate_percent")),
                "amount": _decimal_text(_get(tax, "amount")),
            }
            for tax in bundle.get("taxes", [])
        ],
        "validations": [
            {
                "rule": _get(validation, "rule", ""),
                "passed": _get(validation, "passed", False),
                "severity": _get(validation, "severity", "info"),
                "message": _get(validation, "message", ""),
                "details": _get(validation, "details", {}) or {},
            }
            for validation in bundle.get("validations", [])
        ],
        "risk_flags": [
            {
                "code": _get(risk, "code", ""),
                "points": _get(risk, "points", 0),
                "level": _get(risk, "level", "low"),
                "message": _get(risk, "message", ""),
                "details": _get(risk, "details", {}) or {},
            }
            for risk in bundle.get("risks", [])
        ],
        "extraction": extraction_json,
    }


async def answer_invoice_question(
    question: str,
    bundle: dict[str, Any],
    ocr_text: str,
    assistant_client: VLMClient | None = None,
) -> InvoiceQuestionResponse:
    """Ask Ollama when available, otherwise answer from persisted evidence."""

    clean_question = question.strip()
    invoice_json = build_invoice_context(bundle)
    if assistant_client is not None:
        try:
            if await assistant_client.health_check():
                return await assistant_client.answer_question(
                    clean_question,
                    invoice_json,
                    ocr_text,
                )
        except Exception as exc:
            logger.warning(
                "invoice_assistant_provider_failed",
                provider=assistant_client.name,
                error=str(exc),
            )
    return deterministic_invoice_answer(clean_question, bundle)


def deterministic_invoice_answer(
    question: str,
    bundle: dict[str, Any],
) -> InvoiceQuestionResponse:
    """Answer common AP questions without a model or invented values."""

    invoice = bundle["invoice"]
    vendor = bundle.get("vendor")
    lowered = question.casefold()
    currency = invoice.currency or "INR"

    if "gstin" in lowered:
        value = vendor.gstin if vendor and vendor.gstin else None
        return _answer(
            question,
            value or "GSTIN is not available in the invoice evidence.",
            ["invoice.vendor.gstin"],
        )

    if any(term in lowered for term in ("gst charge", "gst amount", "tax charge", "tax amount")):
        taxes = list(bundle.get("taxes", []))
        if taxes:
            rows = []
            for tax in taxes:
                label = {
                    "CGST_SGST": "CGST + SGST (combined)",
                    "CGST": "CGST",
                    "SGST": "SGST",
                    "IGST": "IGST",
                    "CESS": "CESS",
                }.get(tax.tax_type, tax.tax_type)
                rows.append(f"{label}: {_money(tax.amount, currency)}")
            return _answer(question, "\n".join(rows), ["invoice.taxes"])
        return _answer(question, "No GST charges were extracted.", ["invoice.taxes"])

    if "due" in lowered:
        return _answer(
            question,
            _date_text(invoice.due_date) or "Payment due date is not available.",
            ["invoice.due_date"],
        )

    suspicious_terms = ("suspicious", "suspicion", "anomal", "risk", "issue", "wrong")
    if any(term in lowered for term in suspicious_terms):
        risks = list(bundle.get("risks", []))
        failed_validations = [
            validation for validation in bundle.get("validations", []) if not validation.passed
        ]
        signals = [f"{risk.message} (+{risk.points})" for risk in risks]
        signals.extend(validation.message for validation in failed_validations)
        if signals:
            return _answer(
                question,
                "Review signals: " + "; ".join(signals[:6]),
                ["invoice.risk_flags", "invoice.validations"],
            )
        return _answer(
            question,
            "No suspicious risk or failed-validation signals were found in the invoice evidence.",
            ["invoice.risk_flags", "invoice.validations"],
        )

    if "vendor" in lowered or "supplier" in lowered:
        return _answer(
            question,
            vendor.name if vendor else "Vendor is not available in the invoice evidence.",
            ["invoice.vendor.name"],
        )
    if "po" in lowered or "purchase order" in lowered:
        return _answer(
            question,
            invoice.po_number or "No purchase-order reference was extracted.",
            ["invoice.po_number"],
        )
    if "outstanding" in lowered or "balance" in lowered:
        return _answer(
            question,
            _money(invoice.outstanding_amount, currency),
            ["invoice.outstanding_amount"],
        )
    if "total" in lowered or "amount" in lowered:
        return _answer(
            question,
            _money(invoice.grand_total, currency)
            if invoice.grand_total is not None
            else "Grand total is not available.",
            ["invoice.grand_total"],
        )
    if "status" in lowered or "stage" in lowered:
        return _answer(question, invoice.status, ["invoice.status"])
    if "item" in lowered or "line" in lowered:
        descriptions = [item.description for item in bundle.get("items", []) if item.description]
        return _answer(
            question,
            ", ".join(descriptions) if descriptions else "No line items were extracted.",
            ["invoice.items"],
        )

    return _answer(
        question,
        "Not available in the invoice evidence.",
        ["invoice_json", "ocr_text"],
    )


def _answer(question: str, answer: str, evidence: list[str]) -> InvoiceQuestionResponse:
    return InvoiceQuestionResponse(
        question=question,
        answer=answer,
        evidence=evidence,
        provider="deterministic-rules",
        grounded=True,
    )


def _get(value: Any, name: str, default: Any = None) -> Any:
    return getattr(value, name, default)


def _date_text(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else str(value) if value else None


def _decimal_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _money(value: Decimal | None, currency: str) -> str:
    if value is None:
        return "Not available"
    symbol = "₹" if currency.upper() == "INR" else f"{currency} "
    return f"{symbol}{Decimal(str(value)):,.2f}"
