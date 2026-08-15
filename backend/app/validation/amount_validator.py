"""Financial arithmetic and GST amount consistency validation."""

from decimal import Decimal

from app.domain.schemas import InvoiceExtraction, ValidationFlag, ValidationSeverity
from app.validation.gst_validator import validate_gst_mode

AMOUNT_TOLERANCE = Decimal("1.00")


def validate_amounts(extraction: InvoiceExtraction) -> list[ValidationFlag]:
    """Reconcile subtotal, discount, tax, shipping, and invoice total."""

    return [validate_arithmetic(extraction)]


def validate_arithmetic(extraction: InvoiceExtraction) -> ValidationFlag:
    if extraction.grand_total is None:
        return ValidationFlag(
            rule="arithmetic",
            passed=True,
            message="Arithmetic check skipped (grand total not extracted)",
            severity=ValidationSeverity.INFO,
        )

    line_total = sum((item.line_total for item in extraction.line_items), Decimal("0"))
    subtotal = extraction.subtotal if extraction.subtotal is not None else line_total
    if extraction.subtotal is None and not extraction.line_items:
        return ValidationFlag(
            rule="arithmetic",
            passed=True,
            message="Arithmetic check skipped (no subtotal or line items extracted)",
            severity=ValidationSeverity.INFO,
        )

    discount = extraction.discount_total or Decimal("0")
    taxable_amount = subtotal - discount
    tax_rows_total = sum((tax.amount for tax in extraction.taxes), Decimal("0"))
    tax_amount = tax_rows_total if extraction.taxes else extraction.tax_total
    shipping = extraction.shipping_amount or Decimal("0")
    calculated_total = taxable_amount + tax_amount + shipping
    invoice_total = extraction.grand_total
    difference = invoice_total - calculated_total
    details = {
        "subtotal": str(subtotal),
        "discount": str(discount),
        "taxable_amount": str(taxable_amount),
        "tax": str(tax_amount),
        "shipping": str(shipping),
        "calculated_total": str(calculated_total),
        "invoice_total": str(invoice_total),
        "difference": str(difference),
        "tolerance": str(AMOUNT_TOLERANCE),
    }

    if discount < 0 or subtotal < 0 or taxable_amount < 0:
        return ValidationFlag(
            rule="arithmetic",
            passed=False,
            message=(
                f"Invalid amount components: subtotal {subtotal}, discount {discount}, "
                f"taxable amount {taxable_amount}"
            ),
            severity=ValidationSeverity.WARNING,
            details=details,
        )

    if abs(difference) <= AMOUNT_TOLERANCE:
        return ValidationFlag(
            rule="arithmetic",
            passed=True,
            message=(
                "Mathematical validation passed: "
                f"taxable amount {_display_amount(taxable_amount)} + "
                f"tax {_display_amount(tax_amount)} + shipping {_display_amount(shipping)} "
                f"= calculated {_display_amount(calculated_total)}; "
                f"invoice total {_display_amount(invoice_total)}."
            ),
            severity=ValidationSeverity.INFO,
            details=details,
        )
    symbol = "₹" if extraction.currency.upper() == "INR" else ""
    return ValidationFlag(
        rule="arithmetic",
        passed=False,
        message=(
            f"Total mismatch. Calculated: {symbol}{_display_amount(calculated_total)}; "
            f"Invoice: {symbol}{_display_amount(invoice_total)}; "
            f"Difference: {symbol}{_display_amount(abs(difference))}."
        ),
        severity=ValidationSeverity.WARNING,
        details=details,
    )


def _display_amount(value: Decimal) -> str:
    """Render a currency amount with grouping while keeping useful decimals."""

    rendered = f"{value:,.2f}"
    return rendered.rstrip("0").rstrip(".")


def validate_tax_consistency(extraction: InvoiceExtraction) -> list[ValidationFlag]:
    """Check tax-row totals and split-GST/IGST consistency."""

    if not extraction.taxes:
        return [
            validate_gst_mode(extraction),
            ValidationFlag(
                rule="tax_total",
                passed=True,
                message="Tax total check skipped (no tax rows extracted)",
                severity=ValidationSeverity.INFO,
            ),
        ]

    extracted_tax = sum((tax.amount for tax in extraction.taxes), Decimal("0"))
    flags = [validate_gst_mode(extraction)]
    if (
        extraction.tax_total is not None
        and abs(extracted_tax - extraction.tax_total) > AMOUNT_TOLERANCE
    ):
        flags.append(
            ValidationFlag(
                rule="tax_total",
                passed=False,
                message=(
                    f"Tax rows total {extracted_tax} but extracted tax_total is "
                    f"{extraction.tax_total} (difference: "
                    f"{abs(extracted_tax - extraction.tax_total)})."
                ),
                severity=ValidationSeverity.WARNING,
                details={
                    "tax_rows_total": str(extracted_tax),
                    "tax_total": str(extraction.tax_total),
                    "difference": str(abs(extracted_tax - extraction.tax_total)),
                },
            )
        )
    else:
        flags.append(
            ValidationFlag(
                rule="tax_total",
                passed=True,
                message=f"Tax rows total {extracted_tax}, matching extracted tax_total.",
                severity=ValidationSeverity.INFO,
            )
        )
    return flags
