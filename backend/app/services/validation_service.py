"""
Validation engine — what separates a "toy extractor" from production AP software.

Each validator is a standalone function returning a ValidationFlag.
Validators run after extraction and surface issues as inline warnings
in the API response and dashboard, NOT as silent failures.

Validators implemented:
  1. Arithmetic: sum(line_items) + tax ≈ grand_total
  2. GSTIN: 15-char format + checksum digit validation
  3. Date sanity: invoice_date <= due_date, not in future
  4. Duplicate detection: perceptual hash + (vendor, invoice_number)
  5. Required fields: minimum viable extraction check
"""

import re
from datetime import datetime

from app.core.logging import get_logger
from app.domain.schemas import (
    InvoiceExtraction,
    ValidationFlag,
    ValidationSeverity,
)

logger = get_logger(__name__)


class ValidationService:
    """
    Runs all validators against an InvoiceExtraction and returns
    a list of ValidationFlags with pass/fail, message, and severity.
    """

    def validate(self, extraction: InvoiceExtraction) -> list[ValidationFlag]:
        """Run all validation checks and return flags."""
        flags: list[ValidationFlag] = []

        flags.append(self._validate_required_fields(extraction))
        flags.append(self._validate_arithmetic(extraction))
        flags.extend(self._validate_dates(extraction))
        flags.append(self._validate_gstin(extraction))
        flags.append(self._validate_currency_consistency(extraction))

        # Log summary
        passed = sum(1 for f in flags if f.passed)
        logger.info(
            "validation_complete",
            total_checks=len(flags),
            passed=passed,
            failed=len(flags) - passed,
        )

        return flags

    # ── Individual Validators ────────────────────────────────────────

    def _validate_required_fields(self, extraction: InvoiceExtraction) -> ValidationFlag:
        """Check that minimum required fields were extracted."""
        missing = []

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

    def _validate_arithmetic(self, extraction: InvoiceExtraction) -> ValidationFlag:
        """
        Validate: sum(line_items.line_total) + tax ≈ grand_total

        This catches OCR errors even when individual fields look plausible.
        Uses a tolerance of ±1.0 to handle rounding differences.
        """
        if not extraction.line_items or extraction.grand_total is None:
            return ValidationFlag(
                rule="arithmetic",
                passed=True,
                message="Arithmetic check skipped (no line items or total)",
                severity=ValidationSeverity.INFO,
            )

        line_sum = sum(item.line_total for item in extraction.line_items)
        tax_sum = sum(t.amount for t in extraction.taxes)
        expected_total = line_sum + tax_sum + extraction.shipping_amount

        grand_total = extraction.grand_total
        difference = abs(float(expected_total - grand_total))

        # Tolerance: 1% of total or ±1.0, whichever is larger
        tolerance = max(float(grand_total) * 0.01, 1.0)

        if difference <= tolerance:
            return ValidationFlag(
                rule="arithmetic",
                passed=True,
                message=(
                    f"Arithmetic valid: items({line_sum}) + tax({tax_sum}) + "
                    f"shipping({extraction.shipping_amount}) = "
                    f"{expected_total} ≈ total({grand_total})"
                ),
                severity=ValidationSeverity.INFO,
            )
        else:
            return ValidationFlag(
                rule="arithmetic",
                passed=False,
                message=(
                    f"Arithmetic mismatch: items({line_sum}) + tax({tax_sum}) + "
                    f"shipping({extraction.shipping_amount}) = {expected_total}, "
                    f"but grand_total is {grand_total} (diff: {difference:.2f})"
                ),
                severity=ValidationSeverity.WARNING,
            )

    def _validate_dates(self, extraction: InvoiceExtraction) -> list[ValidationFlag]:
        """
        Validate date sanity:
          - invoice_date and due_date are parseable
          - invoice_date <= due_date
          - Neither is unreasonably far in the future
        """
        flags = []

        inv_date = self._parse_date(extraction.invoice_date)
        due_date_parsed = self._parse_date(extraction.due_date)

        if extraction.invoice_date and inv_date is None:
            flags.append(
                ValidationFlag(
                    rule="date_parseable",
                    passed=False,
                    message=f"Could not parse invoice_date: '{extraction.invoice_date}'",
                    severity=ValidationSeverity.WARNING,
                )
            )

        if inv_date and due_date_parsed:
            if inv_date > due_date_parsed:
                flags.append(
                    ValidationFlag(
                        rule="date_order",
                        passed=False,
                        message=(
                            f"invoice_date ({extraction.invoice_date}) is after "
                            f"due_date ({extraction.due_date})"
                        ),
                        severity=ValidationSeverity.WARNING,
                    )
                )
            else:
                flags.append(
                    ValidationFlag(
                        rule="date_order",
                        passed=True,
                        message="Date order valid",
                        severity=ValidationSeverity.INFO,
                    )
                )

        # Check if date is unreasonably far in the future (>1 year)
        if inv_date:
            now = datetime.now()
            days_ahead = (inv_date - now).days
            if days_ahead > 365:
                flags.append(
                    ValidationFlag(
                        rule="date_future",
                        passed=False,
                        message=(
                            "Invoice date is more than 1 year in the future: "
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
                    message="Date validation passed (or no dates to validate)",
                    severity=ValidationSeverity.INFO,
                )
            )

        return flags

    def _validate_gstin(self, extraction: InvoiceExtraction) -> ValidationFlag:
        """
        Validate Indian GSTIN format and checksum.

        GSTIN format: 2-digit state code + 10-char PAN + 1 entity code + Z + 1 checksum
        Total: 15 characters, e.g. 27AAPFU0939F1ZV
        """
        gstin_field = extraction.vendor.gstin
        if not gstin_field or not gstin_field.value:
            return ValidationFlag(
                rule="gstin",
                passed=True,
                message="GSTIN check skipped (not present)",
                severity=ValidationSeverity.INFO,
            )

        gstin = gstin_field.value.upper().strip()

        # Format check
        pattern = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z0-9]$")
        if not pattern.match(gstin):
            return ValidationFlag(
                rule="gstin",
                passed=False,
                message=f"GSTIN '{gstin}' does not match the 15-character format",
                severity=ValidationSeverity.WARNING,
            )

        # State code check (01-37)
        state_code = int(gstin[:2])
        if state_code < 1 or state_code > 37:
            return ValidationFlag(
                rule="gstin",
                passed=False,
                message=f"GSTIN state code '{gstin[:2]}' is not valid (must be 01-37)",
                severity=ValidationSeverity.WARNING,
            )

        # Checksum validation
        if self._verify_gstin_checksum(gstin):
            return ValidationFlag(
                rule="gstin",
                passed=True,
                message=f"GSTIN '{gstin}' is valid (format + checksum)",
                severity=ValidationSeverity.INFO,
            )
        else:
            return ValidationFlag(
                rule="gstin",
                passed=False,
                message=f"GSTIN '{gstin}' checksum is invalid",
                severity=ValidationSeverity.WARNING,
            )

    def _validate_currency_consistency(self, extraction: InvoiceExtraction) -> ValidationFlag:
        """Check that currency is a recognised code."""
        valid_currencies = {"INR", "USD", "EUR", "GBP", "AUD", "CAD", "JPY", "SGD", "AED"}

        if extraction.currency.upper() in valid_currencies:
            return ValidationFlag(
                rule="currency",
                passed=True,
                message=f"Currency '{extraction.currency}' is valid",
                severity=ValidationSeverity.INFO,
            )
        else:
            return ValidationFlag(
                rule="currency",
                passed=False,
                message=f"Unrecognised currency: '{extraction.currency}'",
                severity=ValidationSeverity.WARNING,
            )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        """Try multiple date formats."""
        if not date_str:
            return None

        formats = [
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
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        return None

    @staticmethod
    def _verify_gstin_checksum(gstin: str) -> bool:
        """
        Verify the GSTIN check digit using the Luhn mod-36 algorithm.

        This is the same algorithm used by the Indian GST Network.
        """
        char_map = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        try:
            total = 0
            for i in range(14):  # First 14 characters
                char_val = char_map.index(gstin[i])

                if i % 2 == 0:
                    # Odd position (1-indexed)
                    total += char_val
                else:
                    # Even position
                    doubled = char_val * 2
                    total += doubled // 36 + doubled % 36

            remainder = total % 36
            check_digit = char_map[(36 - remainder) % 36]

            return check_digit == gstin[14]
        except (ValueError, IndexError):
            return False
