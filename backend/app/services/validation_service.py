"""Validation orchestration for the provider-independent invoice rules."""

from collections.abc import Iterable

from app.core.logging import get_logger
from app.domain.schemas import InvoiceExtraction, ValidationFlag
from app.validation.amount_validator import validate_amounts, validate_tax_consistency
from app.validation.date_validator import parse_invoice_date, validate_dates
from app.validation.duplicate_validator import validate_duplicate
from app.validation.gst_validator import validate_gstins, verify_gstin_checksum
from app.validation.invoice_validator import validate_currency, validate_required_fields
from app.validation.pan_validator import validate_pans

logger = get_logger(__name__)


class ValidationService:
    """Run all validation families and return explainable review flags."""

    def validate(
        self,
        extraction: InvoiceExtraction,
        duplicate_keys: Iterable[tuple[str, str]] | None = None,
    ) -> list[ValidationFlag]:
        """Run invoice, amount, date, GST, PAN, and duplicate checks."""

        flags: list[ValidationFlag] = [
            self._validate_required_fields(extraction),
            self._validate_arithmetic(extraction),
        ]
        flags.extend(self._validate_dates(extraction))
        flags.extend(self._validate_gstins(extraction))
        flags.extend(self._validate_pans(extraction))
        flags.extend(self._validate_tax_consistency(extraction))
        flags.append(self._validate_currency_consistency(extraction))
        flags.append(self._validate_duplicate(extraction, duplicate_keys))

        passed = sum(1 for flag in flags if flag.passed)
        logger.info(
            "validation_complete",
            total_checks=len(flags),
            passed=passed,
            failed=len(flags) - passed,
        )
        return flags

    # Compatibility wrappers keep the existing service surface stable for
    # callers that used the previous private rule methods.
    def _validate_required_fields(self, extraction: InvoiceExtraction) -> ValidationFlag:
        return validate_required_fields(extraction)

    def _validate_arithmetic(self, extraction: InvoiceExtraction) -> ValidationFlag:
        return validate_amounts(extraction)[0]

    def _validate_dates(self, extraction: InvoiceExtraction) -> list[ValidationFlag]:
        return validate_dates(extraction)

    def _validate_gstins(self, extraction: InvoiceExtraction) -> list[ValidationFlag]:
        return validate_gstins(extraction)

    def _validate_gstin(self, extraction: InvoiceExtraction) -> ValidationFlag:
        return self._validate_gstins(extraction)[0]

    def _validate_pans(self, extraction: InvoiceExtraction) -> list[ValidationFlag]:
        return validate_pans(extraction)

    def _validate_pan(self, extraction: InvoiceExtraction) -> ValidationFlag:
        return self._validate_pans(extraction)[0]

    def _validate_tax_consistency(self, extraction: InvoiceExtraction) -> list[ValidationFlag]:
        return validate_tax_consistency(extraction)

    def _validate_currency_consistency(self, extraction: InvoiceExtraction) -> ValidationFlag:
        return validate_currency(extraction)

    def _validate_duplicate(
        self,
        extraction: InvoiceExtraction,
        duplicate_keys: Iterable[tuple[str, str]] | None = None,
    ) -> ValidationFlag:
        return validate_duplicate(extraction, duplicate_keys)

    @staticmethod
    def _parse_date(date_str: str | None):
        """Compatibility alias for the shared date parser."""

        return parse_invoice_date(date_str)

    @staticmethod
    def _verify_gstin_checksum(gstin: str) -> bool:
        """Compatibility alias for the shared GST checksum implementation."""

        return verify_gstin_checksum(gstin)
