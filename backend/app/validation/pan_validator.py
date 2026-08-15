"""Local PAN syntax validation for seller and buyer fields."""

from app.domain.schemas import InvoiceExtraction, ValidationFlag, ValidationSeverity
from app.extraction.pan import is_valid_pan, normalize_pan


def validate_pans(extraction: InvoiceExtraction) -> list[ValidationFlag]:
    flags = [_validate_pan_field(extraction.vendor.pan, "PAN", "pan")]
    if extraction.buyer and extraction.buyer.pan and extraction.buyer.pan.value:
        flags.append(_validate_pan_field(extraction.buyer.pan, "buyer PAN", "buyer_pan"))
    return flags


def _validate_pan_field(field, label: str, rule: str) -> ValidationFlag:
    if not field or not field.value:
        return ValidationFlag(
            rule=rule,
            passed=True,
            message=f"{label} check skipped (not present)",
            severity=ValidationSeverity.INFO,
        )
    pan = normalize_pan(field.value)
    field.value = pan
    if is_valid_pan(pan):
        return ValidationFlag(
            rule=rule,
            passed=True,
            message=(
                f"{label} '{pan}' matches the expected syntax "
                "(local syntax check only; not a government verification)"
            ),
            severity=ValidationSeverity.INFO,
        )
    return ValidationFlag(
        rule=rule,
        passed=False,
        message=f"{label} '{pan}' does not match the expected 10-character syntax",
        severity=ValidationSeverity.WARNING,
    )
