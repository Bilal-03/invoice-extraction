"""Fingerprint and business-key duplicate validation.

Database-backed duplicate detection remains in the AP projection because it
needs tenant-scoped database state. This module provides reusable fingerprint
and pure validation rules for callers with existing invoice keys.

The primary fingerprint is deliberately deterministic and explainable:
supplier GSTIN + normalized invoice number + normalized invoice date +
normalized grand total. A legacy vendor-name/invoice-number key remains as a
fallback for older records or invoices where the required fingerprint fields
were not extracted.
"""

import hashlib
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from app.domain.schemas import InvoiceExtraction, ValidationFlag, ValidationSeverity
from app.extraction.gst import normalize_gstin
from app.validation.date_validator import parse_invoice_date


def duplicate_fingerprint_components(
    extraction: InvoiceExtraction,
) -> dict[str, str] | None:
    """Return canonical fingerprint inputs when all required evidence exists."""

    supplier_gstin = normalize_gstin(
        extraction.vendor.gstin.value if extraction.vendor.gstin else ""
    )
    invoice_number = normalize_key(extraction.invoice_number.value)
    parsed_date = parse_invoice_date(extraction.invoice_date)
    grand_total = _canonical_amount(extraction.grand_total)
    if not supplier_gstin or not invoice_number or parsed_date is None or grand_total is None:
        return None
    return {
        "supplier_gstin": supplier_gstin,
        "invoice_number": invoice_number,
        "invoice_date": parsed_date.date().isoformat(),
        "grand_total": grand_total,
    }


def duplicate_fingerprint(extraction: InvoiceExtraction) -> str | None:
    """Create a SHA-256 fingerprint for the canonical invoice identity."""

    components = duplicate_fingerprint_components(extraction)
    if components is None:
        return None
    canonical = "|".join(
        (
            components["supplier_gstin"],
            components["invoice_number"],
            components["invoice_date"],
            components["grand_total"],
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def duplicate_key(extraction: InvoiceExtraction) -> tuple[str, str] | None:
    """Return the legacy vendor-name/invoice-number fallback key."""

    vendor = normalize_key(extraction.vendor.name.value)
    number = normalize_key(extraction.invoice_number.value)
    if not vendor or not number:
        return None
    return vendor, number


def validate_duplicate(
    extraction: InvoiceExtraction,
    existing_keys: Iterable[tuple[str, str]] | None = None,
    existing_fingerprints: Iterable[str] | None = None,
) -> ValidationFlag:
    """Check a fingerprint or legacy key when prior records are supplied."""

    fingerprint = duplicate_fingerprint(extraction)
    if existing_fingerprints is not None and fingerprint in set(existing_fingerprints):
        return ValidationFlag(
            rule="duplicate_invoice",
            passed=False,
            message="Possible Duplicate Invoice: matching invoice fingerprint found",
            severity=ValidationSeverity.ERROR,
            details={"fingerprint": fingerprint, "match_type": "sha256_fingerprint"},
        )

    key = duplicate_key(extraction)
    if existing_keys is None and existing_fingerprints is None:
        return ValidationFlag(
            rule="duplicate_invoice",
            passed=True,
            message="Duplicate check deferred to tenant-scoped AP database matching",
            severity=ValidationSeverity.INFO,
        )
    if key is None:
        return ValidationFlag(
            rule="duplicate_invoice",
            passed=True,
            message="Duplicate check skipped (vendor and invoice number are required)",
            severity=ValidationSeverity.INFO,
        )
    if existing_keys is not None and key in set(existing_keys):
        return ValidationFlag(
            rule="duplicate_invoice",
            passed=False,
            message=(
                f"Possible duplicate invoice for vendor '{extraction.vendor.name.value}' "
                f"and invoice number '{extraction.invoice_number.value}'"
            ),
            severity=ValidationSeverity.ERROR,
            details={"vendor_key": key[0], "invoice_number_key": key[1]},
        )
    return ValidationFlag(
        rule="duplicate_invoice",
        passed=True,
        message="No duplicate found in supplied invoice keys",
        severity=ValidationSeverity.INFO,
    )


def normalize_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _canonical_amount(value: Decimal | None) -> str | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return format(amount, "f")
