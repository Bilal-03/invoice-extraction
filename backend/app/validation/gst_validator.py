"""Local GSTIN syntax and GST-mode consistency checks.

These rules are automated consistency checks only. They do not call a GST API
and do not claim legal GST compliance or registration status.
"""

import re

from app.domain.schemas import InvoiceExtraction, TaxType, ValidationFlag, ValidationSeverity
from app.extraction.gst import is_valid_gstin_syntax, normalize_gstin


def validate_gstins(extraction: InvoiceExtraction) -> list[ValidationFlag]:
    """Validate seller and, when present, buyer GSTIN format/checksum locally."""

    flags = [_validate_gstin_field(extraction.vendor.gstin, "GSTIN", "gstin")]
    if extraction.buyer and extraction.buyer.gstin and extraction.buyer.gstin.value:
        flags.append(_validate_gstin_field(extraction.buyer.gstin, "buyer GSTIN", "buyer_gstin"))
    return flags


def _validate_gstin_field(field, label: str, rule: str) -> ValidationFlag:
    if not field or not field.value:
        return ValidationFlag(
            rule=rule,
            passed=True,
            message=f"{label} check skipped (not present)",
            severity=ValidationSeverity.INFO,
        )

    gstin = normalize_gstin(field.value)
    field.value = gstin
    if not is_valid_gstin_syntax(gstin):
        return ValidationFlag(
            rule=rule,
            passed=False,
            message=f"{label} '{gstin}' does not match the 15-character format",
            severity=ValidationSeverity.WARNING,
        )

    state_code = int(gstin[:2])
    if state_code < 1 or state_code > 37:
        return ValidationFlag(
            rule=rule,
            passed=False,
            message=f"{label} state code '{gstin[:2]}' is not valid (must be 01-37)",
            severity=ValidationSeverity.WARNING,
        )

    if not verify_gstin_checksum(gstin):
        return ValidationFlag(
            rule=rule,
            passed=False,
            message=f"{label} '{gstin}' checksum is invalid",
            severity=ValidationSeverity.WARNING,
        )
    return ValidationFlag(
        rule=rule,
        passed=True,
        message=(
            f"{label} '{gstin}' passed the local format, state-code, and checksum check "
            "(not a legal registration verification)"
        ),
        severity=ValidationSeverity.INFO,
    )


def validate_gst_mode(extraction: InvoiceExtraction) -> ValidationFlag:
    """Check split GST versus IGST against available state evidence."""

    tax_types = {tax.tax_type for tax in extraction.taxes}
    has_igst = TaxType.IGST in tax_types
    has_cgst = TaxType.CGST in tax_types
    has_sgst = TaxType.SGST in tax_types
    has_combined_split = TaxType.CGST_SGST in tax_types
    has_split = has_combined_split or has_cgst or has_sgst
    disclaimer = "Automated consistency check only; not legal GST compliance verification."

    if not extraction.taxes:
        return ValidationFlag(
            rule="gst_mode_consistency",
            passed=True,
            message=f"GST mode check skipped (no tax rows extracted). {disclaimer}",
            severity=ValidationSeverity.INFO,
        )
    if has_igst and has_split:
        return ValidationFlag(
            rule="gst_mode_consistency",
            passed=False,
            message=f"Invoice contains both IGST and split CGST/SGST rows. {disclaimer}",
            severity=ValidationSeverity.WARNING,
        )
    if (has_cgst and not has_sgst) or (has_sgst and not has_cgst):
        return ValidationFlag(
            rule="gst_mode_consistency",
            passed=False,
            message=f"CGST and SGST are not present as a complete pair. {disclaimer}",
            severity=ValidationSeverity.WARNING,
        )

    seller_state = _gstin_state(extraction.vendor.gstin.value if extraction.vendor.gstin else None)
    buyer_state = _gstin_state(
        extraction.buyer.gstin.value if extraction.buyer and extraction.buyer.gstin else None
    ) or _place_of_supply_state(extraction.place_of_supply)
    expected = None
    if seller_state and buyer_state:
        expected = "IGST" if seller_state != buyer_state else "CGST_SGST"

    actual = "IGST" if has_igst else "CGST_SGST" if has_split else None
    details = {
        "seller_state": seller_state,
        "buyer_or_supply_state": buyer_state,
        "expected_mode": expected,
        "actual_mode": actual,
    }
    if expected and actual and expected != actual:
        return ValidationFlag(
            rule="gst_mode_consistency",
            passed=False,
            message=(
                f"Extracted GST mode is {actual}, but available state evidence suggests "
                f"{expected}. {disclaimer}"
            ),
            severity=ValidationSeverity.WARNING,
            details=details,
        )
    return ValidationFlag(
        rule="gst_mode_consistency",
        passed=True,
        message=(f"GST mode is internally consistent ({actual or 'unspecified'}). {disclaimer}"),
        severity=ValidationSeverity.INFO,
        details=details,
    )


def _gstin_state(value: str | None) -> str | None:
    normalized = normalize_gstin(value or "")
    return normalized[:2] if is_valid_gstin_syntax(normalized) else None


def _place_of_supply_state(value: str | None) -> str | None:
    match = re.search(r"(?<!\d)(\d{2})(?!\d)", value or "")
    return match.group(1) if match else None


def verify_gstin_checksum(gstin: str) -> bool:
    char_map = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    try:
        total = 0
        for index in range(14):
            char_value = char_map.index(gstin[index])
            if index % 2 == 0:
                total += char_value
            else:
                doubled = char_value * 2
                total += doubled // 36 + doubled % 36
        return char_map[(36 - total % 36) % 36] == gstin[14]
    except (ValueError, IndexError):
        return False
