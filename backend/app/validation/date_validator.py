"""Invoice and due-date validation."""

from datetime import datetime, timedelta

from dateutil import parser as date_parser

from app.domain.schemas import InvoiceExtraction, ValidationFlag, ValidationSeverity


def parse_invoice_date(value: str | None) -> datetime | None:
    """Parse common Indian invoice date formats without changing the source text."""

    if not value:
        return None
    formats = (
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%m.%d.%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    )
    text = value.strip()
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return date_parser.parse(text, dayfirst=True, fuzzy=False)
    except (ValueError, OverflowError, TypeError):
        return None


def validate_dates(extraction: InvoiceExtraction) -> list[ValidationFlag]:
    """Validate parseability, invoice/due ordering, and implausible invoice dates."""

    flags: list[ValidationFlag] = []
    invoice_date = parse_invoice_date(extraction.invoice_date)
    due_date = parse_invoice_date(extraction.due_date)

    if extraction.invoice_date and invoice_date is None:
        flags.append(
            ValidationFlag(
                rule="date_parseable",
                passed=False,
                message=f"Could not parse invoice_date: '{extraction.invoice_date}'",
                severity=ValidationSeverity.WARNING,
            )
        )
    if extraction.due_date and due_date is None:
        flags.append(
            ValidationFlag(
                rule="due_date_parseable",
                passed=False,
                message=f"Could not parse due_date: '{extraction.due_date}'",
                severity=ValidationSeverity.WARNING,
            )
        )

    if invoice_date and due_date:
        if invoice_date > due_date:
            flags.append(
                ValidationFlag(
                    rule="date_order",
                    passed=False,
                    message="Due date occurs before invoice date",
                    severity=ValidationSeverity.WARNING,
                    details={
                        "invoice_date": invoice_date.date().isoformat(),
                        "due_date": due_date.date().isoformat(),
                        "difference_days": (invoice_date - due_date).days,
                    },
                )
            )
        else:
            flags.append(
                ValidationFlag(
                    rule="date_order",
                    passed=True,
                    message="Invoice date is on or before the due date",
                    severity=ValidationSeverity.INFO,
                )
            )

    if invoice_date and invoice_date.date() > datetime.now().date() + timedelta(days=365):
        flags.append(
            ValidationFlag(
                rule="date_future",
                passed=False,
                message=(
                    "Invoice date is more than one year in the future: "
                    f"{extraction.invoice_date}"
                ),
                severity=ValidationSeverity.WARNING,
            )
        )

    if not flags:
        flags.append(
            ValidationFlag(
                rule="date_sanity",
                passed=True,
                message="Date validation passed (or no dates were supplied)",
                severity=ValidationSeverity.INFO,
            )
        )
    return flags
