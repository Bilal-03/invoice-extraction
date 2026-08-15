"""Invoice-level validation rules that do not depend on one field family."""

from app.domain.schemas import InvoiceExtraction, ValidationFlag, ValidationSeverity

VALID_CURRENCIES = {"INR", "USD", "EUR", "GBP", "AUD", "CAD", "JPY", "SGD", "AED"}


def validate_required_fields(extraction: InvoiceExtraction) -> ValidationFlag:
    """Check the minimum fields needed to route an invoice for review."""

    missing: list[str] = []
    if not extraction.invoice_number.value:
        missing.append("invoice_number")
    if not extraction.vendor.name.value:
        missing.append("vendor_name")
    if extraction.grand_total is None:
        missing.append("grand_total")

    if missing:
        return ValidationFlag(
            rule="required_fields",
            passed=False,
            message=f"Missing required fields: {', '.join(missing)}",
            severity=ValidationSeverity.ERROR,
        )
    return ValidationFlag(
        rule="required_fields",
        passed=True,
        message="All required fields present",
        severity=ValidationSeverity.INFO,
    )


def validate_currency(extraction: InvoiceExtraction) -> ValidationFlag:
    """Check that the extracted currency is one of the supported display codes."""

    currency = (extraction.currency or "").upper()
    if currency in VALID_CURRENCIES:
        return ValidationFlag(
            rule="currency",
            passed=True,
            message=f"Currency '{extraction.currency}' is valid",
            severity=ValidationSeverity.INFO,
        )
    return ValidationFlag(
        rule="currency",
        passed=False,
        message=f"Unrecognised currency: '{extraction.currency}'",
        severity=ValidationSeverity.WARNING,
    )
