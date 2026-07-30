"""
Enhanced regex field extractor with spatial awareness.

This is a major upgrade from the original app.py's flat regex approach:
  1. Uses word-level bounding boxes from OCR (spatial context)
  2. Multiple regex patterns per field with priority scoring
  3. Context-aware extraction (e.g. "Total" near a number = total amount)
  4. Per-field confidence scoring
  5. Line-item table extraction

The spatial awareness is what allows extraction to work across different
invoice layouts — instead of "find any date-shaped string," it's
"find a date-shaped string near a label that says 'Invoice Date'."
"""

import re
from decimal import Decimal, InvalidOperation

from app.adapters.ocr.base import OCRResult, OCRWord
from app.core.logging import get_logger
from app.domain.schemas import (
    BoundingBox,
    BuyerDetails,
    ExtractionSource,
    FieldValue,
    InvoiceExtraction,
    LineItem,
    TaxDetails,
    TaxType,
    VendorDetails,
)
from app.services.extractors.amounts import AmountExtractor
from app.services.extractors.dates import DateExtractor
from app.services.extractors.line_items import LineItemExtractor
from app.services.extractors.parties import PartyExtractor

logger = get_logger(__name__)


# ── Regex Pattern Library ────────────────────────────────────────────

# Invoice number patterns (ordered by specificity — most specific first)
INVOICE_NUMBER_PATTERNS = [
    re.compile(
        r"(?:invoice|inv|bill)\s*(?:number|num|no\.?|#)[.:#\-\s]*([A-Z0-9][\w\-/]+)",
        re.IGNORECASE,
    ),
    re.compile(r"\binv(?:oice)?[.\-#:\s]+([A-Z0-9][\w\-/]+)", re.IGNORECASE),
    re.compile(r"(?i)(?:invoice|bill)\s*[:\s]+([A-Z0-9][\w\-/]+)"),
    re.compile(r"\b([A-Z]{2,4}[-/]\d{4,}[-/]?\d*)\b"),  # e.g. INV-2024-001
]

# Date patterns
DATE_PATTERNS = [
    re.compile(r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})"),  # DD/MM/YYYY or MM/DD/YYYY
    re.compile(r"(\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})"),  # YYYY/MM/DD
    re.compile(r"(\w+\s+\d{1,2},?\s+\d{4})"),  # January 15, 2024
    re.compile(r"(\d{1,2}\s+\w+\s+\d{4})"),  # 15 January 2024
]

# Invoice date context labels
INVOICE_DATE_LABELS = [
    "invoice date",
    "inv date",
    "date of invoice",
    "billing date",
    "invoice dt",
    "dated",
    "date:",
]

DUE_DATE_LABELS = [
    "due date",
    "payment due",
    "due by",
    "pay by",
    "due on",
    "payment date",
    "due dt",
]

# Amount patterns
AMOUNT_PATTERNS = [
    re.compile(r"[\$₹€£]?\s*([\d,]+\.\d{2})\b"),
    re.compile(r"([\d,]+\.\d{2})\s*[\$₹€£]?"),
    re.compile(r"[\$₹€£]\s*([\d,]+)(?:\.\d{2})?\b"),
]

TOTAL_LABELS = [
    "grand total",
    "total amount",
    "total due",
    "amount due",
    "balance due",
    "net amount",
    "total payable",
    "amount payable",
    "total:",
    "total",
]

SUBTOTAL_LABELS = [
    "subtotal",
    "sub total",
    "sub-total",
    "amount before tax",
    "taxable amount",
    "net total",
]

# Tax patterns
GSTIN_PATTERN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z0-9])\b")
TAX_RATE_PATTERN = re.compile(
    r"(?:GST|CGST|SGST|IGST|VAT|tax)\s*[@:]\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE
)

# Currency detection
CURRENCY_MAP = {
    "$": "USD",
    "₹": "INR",
    "€": "EUR",
    "£": "GBP",
    "USD": "USD",
    "INR": "INR",
    "EUR": "EUR",
    "GBP": "GBP",
    "Rs": "INR",
    "Rs.": "INR",
}


class FieldExtractor:
    """
    Enhanced field extraction using regex patterns with spatial awareness
    from OCR bounding boxes.
    """

    def extract(self, ocr_result: OCRResult) -> InvoiceExtraction:
        """Run all extractors and compose the InvoiceExtraction result."""
        self._ocr_result = ocr_result
        text = ocr_result.raw_text
        words = ocr_result.words
        lines = ocr_result.lines()

        # Family boundaries are explicit even while the mature regex matchers
        # remain on this compatibility class. Each family can now move behind
        # its own protocol implementation without changing the schema.
        dates = DateExtractor(self).extract(ocr_result)
        parties = PartyExtractor(self).extract(ocr_result)
        amounts = AmountExtractor(self).extract(ocr_result)
        line_items = LineItemExtractor(self).extract(ocr_result)

        # Extract each field group
        invoice_number = self._extract_invoice_number(text, words)
        invoice_date = dates["invoice_date"]
        due_date = dates["due_date"]
        po_reference = self._extract_labeled_value(
            text,
            [
                r"order\s*(?:no|number|#)?\s*[:\-]\s*"
                r"(\d{3}-\d{7}-\d{4,7}(?:\s+\d{1,3})?)",
                r"(?:PO|purchase order|order)\s*(?:no|number|#)?\s*[:\-]\s*"
                r"([A-Z0-9][A-Z0-9\-/ ]*?)(?=\s{2,}|\n|$)",
            ],
        )
        if po_reference and po_reference.value:
            po_reference.value = po_reference.value.replace(" ", "")
        payment_terms = self._extract_labeled_text(
            text, r"(?:payment terms?|terms)\s*[:\-]\s*([^\n\r]{2,80})"
        )
        vendor = parties["vendor"]
        buyer = parties["buyer"]
        taxes = amounts["taxes"]
        grand_total = amounts["grand_total"]
        subtotal = amounts["subtotal"]
        subtotal_value = (
            Decimal(str(self._parse_number(subtotal.value)))
            if subtotal and subtotal.value
            else sum((item.line_total for item in line_items), Decimal("0")) or None
        )
        tax_total = sum((tax.amount for tax in taxes), Decimal("0"))
        discount_total = sum((item.discount for item in line_items), Decimal("0"))
        shipping_amount = amounts["shipping_amount"]
        if (
            grand_total is not None
            and subtotal_value is not None
            and tax_total > 0
            and grand_total == subtotal_value
        ):
            # OCR often loses the TOTAL/Invoice Value label and the generic
            # amount fallback selects the pre-tax net amount. The table's
            # independently reconstructed arithmetic is stronger evidence.
            grand_total = subtotal_value + tax_total + shipping_amount
        currency = amounts["currency"]

        # Compute overall confidence
        field_confidences = [
            invoice_number.confidence,
            0.9 if grand_total is not None else 0.0,
        ]
        if vendor.name.value:
            field_confidences.append(vendor.name.confidence)
        if invoice_date:
            field_confidences.append(0.8)

        overall = sum(field_confidences) / max(len(field_confidences), 1)

        extraction = InvoiceExtraction(
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            po_reference=po_reference,
            payment_terms=payment_terms,
            vendor=vendor,
            buyer=buyer,
            line_items=line_items,
            taxes=taxes,
            subtotal=subtotal_value,
            discount_total=discount_total,
            tax_total=tax_total,
            shipping_amount=shipping_amount,
            grand_total=grand_total,
            currency=currency,
            overall_confidence=round(overall, 3),
            extraction_source=ExtractionSource.OCR_REGEX,
        )

        logger.info(
            "field_extraction_complete",
            invoice_number=invoice_number.value,
            vendor=vendor.name.value,
            grand_total=str(extraction.grand_total),
            confidence=extraction.overall_confidence,
            line_item_count=len(line_items),
        )

        return extraction

    # ── Individual Field Extractors ──────────────────────────────────

    def _extract_invoice_number(self, text: str, words: list[OCRWord]) -> FieldValue:
        """Extract invoice number with multi-pattern matching."""
        for i, pattern in enumerate(INVOICE_NUMBER_PATTERNS):
            match = pattern.search(text)
            if match:
                value = match.group(1).strip()
                # Higher confidence for more specific patterns
                confidence = max(0.5, 0.95 - i * 0.1)
                return self._field_value(value, confidence)

        return FieldValue(value=None, confidence=0.0, source=ExtractionSource.OCR_REGEX)

    def _extract_date(
        self,
        text: str,
        words: list[OCRWord],
        context_labels: list[str],
        *,
        allow_fallback: bool = True,
    ) -> str | None:
        """
        Extract a date using context labels (spatial awareness).

        Instead of "find any date" (which picks up random dates),
        this looks for dates NEAR a specific label like "Invoice Date".
        """
        text_lower = text.lower()

        for label in context_labels:
            label_pos = text_lower.find(label)
            if label_pos == -1:
                continue

            # Look for a date pattern within 100 chars after the label
            search_region = text[label_pos : label_pos + 100]
            for pattern in DATE_PATTERNS:
                match = pattern.search(search_region)
                if match:
                    return match.group(1).strip()

        if allow_fallback:
            # An unlabeled date is useful for invoice date, but must never be
            # silently copied into due date when no due-date context exists.
            for pattern in DATE_PATTERNS:
                match = pattern.search(text)
                if match:
                    return match.group(1).strip()

        return None

    def _extract_vendor(
        self,
        text: str,
        words: list[OCRWord],
        lines: list[list[OCRWord]],
    ) -> VendorDetails:
        """
        Extract vendor details.

        Priority:
          1. Look for a "Sold By" label (e-commerce invoices like Amazon)
          2. Fall back to first substantial line in the document header
        GSTIN is validated against the 15-character GST format.
        """
        vendor_name = None
        vendor_address = None
        gstin = None

        gstin_candidate = re.search(
            r"(?:GST(?:IN|\s+Registration)?(?:\s+No)?\s*[:#-]?\s*)"
            r"([A-Z0-9]{15})",
            text,
            re.IGNORECASE,
        )
        if not gstin_candidate:
            gstin_candidate = GSTIN_PATTERN.search(text)
        if gstin_candidate:
            normalized_gstin = self._normalize_gstin(gstin_candidate.group(1))
            gstin = self._field_value(
                normalized_gstin,
                0.95 if GSTIN_PATTERN.fullmatch(normalized_gstin) else 0.75,
            )

        section = self._extract_section(
            text,
            labels=("sold by", "seller", "supplier", "vendor"),
            stop_labels=(
                "billing address",
                "bill to",
                "shipping address",
                "ship to",
                "order number",
                "invoice number",
                "description",
            ),
        )
        spatial_section = self._extract_spatial_section(
            lines,
            labels=("sold by", "seller", "supplier", "vendor"),
            side="left",
            stop_labels=("pan no", "gst registration", "order number"),
        )
        if spatial_section:
            section = spatial_section
        if section:
            meaningful = [
                line
                for line in section
                if not re.match(r"(?i)^(pan|gst|tax id|vat)\s*(?:no|number)?\s*[:#]", line)
            ]
            if meaningful:
                vendor_name = self._field_value(meaningful[0].lstrip("*•- "), 0.94)
                address_lines = [
                    line.lstrip("*•- ")
                    for line in meaningful[1:]
                    if not re.match(r"(?i)^(pan|gst|tax id|vat)\b", line)
                ]
                if address_lines:
                    vendor_address = self._field_value(", ".join(address_lines), 0.9)

        # 2. Fallback: first substantial non-empty line in the document header
        if vendor_name is None:
            text_lines = text.split("\n")
            for line in text_lines[:8]:
                cleaned = line.strip()
                if len(cleaned) > 3 and not any(
                    kw in cleaned.lower()
                    for kw in [
                        "invoice",
                        "tax",
                        "bill",
                        "date",
                        "gst",
                        "page",
                        "original",
                        "recipient",
                        "supply",
                        "cash memo",
                    ]
                ):
                    vendor_name = self._field_value(cleaned, 0.6)
                    break

        if vendor_name is None:
            vendor_name = FieldValue(value=None, confidence=0.0, source=ExtractionSource.OCR_REGEX)

        return VendorDetails(
            name=vendor_name,
            address=vendor_address,
            gstin=gstin,
        )

    def _extract_buyer(
        self, text: str, lines: list[list[OCRWord]] | None = None
    ) -> BuyerDetails | None:
        """Extract buyer identity plus distinct billing and shipping addresses."""
        billing = self._extract_section(
            text,
            labels=("billing address", "bill to", "buyer", "customer"),
            stop_labels=(
                "shipping address",
                "ship to",
                "place of supply",
                "order number",
                "invoice number",
                "description",
            ),
        )
        shipping = self._extract_section(
            text,
            labels=("shipping address", "ship to", "delivery address"),
            stop_labels=(
                "place of supply",
                "place of delivery",
                "order number",
                "invoice number",
                "description",
            ),
        )
        if lines:
            spatial_billing = self._extract_spatial_section(
                lines,
                labels=("billing address", "bill to"),
                side="right",
                stop_labels=("shipping address", "place of supply", "order number"),
            )
            spatial_shipping = self._extract_spatial_section(
                lines,
                labels=("shipping address", "ship to", "delivery address"),
                side="right",
                stop_labels=("place of supply", "place of delivery", "order number"),
            )
            if spatial_billing:
                billing = spatial_billing
            if spatial_shipping:
                shipping = spatial_shipping
        if not billing and not shipping:
            return None

        name_line = billing[0] if billing else shipping[0]
        billing_address = self._party_address(billing)
        shipping_address = self._party_address(shipping)
        return BuyerDetails(
            name=self._field_value(name_line, 0.9) if name_line else None,
            billing_address=(self._field_value(billing_address, 0.88) if billing_address else None),
            shipping_address=(
                self._field_value(shipping_address, 0.88) if shipping_address else None
            ),
        )

    @staticmethod
    def _party_address(lines: list[str]) -> str | None:
        if not lines:
            return None
        address_lines = [
            line
            for line in lines[1:]
            if not re.match(r"(?i)^(state/ut code|place of supply|place of delivery)\s*:", line)
        ]
        return ", ".join(address_lines) or None

    @staticmethod
    def _extract_section(
        text: str,
        *,
        labels: tuple[str, ...],
        stop_labels: tuple[str, ...],
        max_lines: int = 12,
    ) -> list[str]:
        """Return cleaned lines after a labeled block without crossing sections."""
        source_lines = text.splitlines()
        label_pattern = re.compile(
            rf"^\s*(?:{'|'.join(re.escape(label) for label in labels)})\b\s*:?[ \t]*(.*)$",
            re.IGNORECASE,
        )
        stop_pattern = re.compile(
            rf"^\s*(?:{'|'.join(re.escape(label) for label in stop_labels)})\b",
            re.IGNORECASE,
        )
        for index, source_line in enumerate(source_lines):
            match = label_pattern.match(source_line)
            if not match:
                continue
            collected: list[str] = []
            remainder = match.group(1).strip()
            # A second label on the same OCR line means two columns were
            # flattened together; it is not party data.
            if remainder and not re.search(r"(?i)\b(?:billing|shipping)\s+address\s*:", remainder):
                collected.append(remainder)
            for candidate in source_lines[index + 1 : index + 1 + max_lines]:
                cleaned = re.sub(r"\s+", " ", candidate).strip()
                if not cleaned:
                    if collected:
                        break
                    continue
                if stop_pattern.match(cleaned):
                    break
                collected.append(cleaned)
            if collected:
                return collected
        return []

    def _extract_spatial_section(
        self,
        lines: list[list[OCRWord]],
        *,
        labels: tuple[str, ...],
        side: str,
        stop_labels: tuple[str, ...],
        max_lines: int = 15,
    ) -> list[str]:
        """Reconstruct a labeled left/right column from OCR coordinates."""
        if not lines:
            return []
        anchor_index = None
        anchor_page = 0
        for index, line in enumerate(lines):
            line_text = " ".join(word.text for word in line).lower()
            if any(label in line_text for label in labels):
                anchor_index = index
                anchor_page = line[0].page if line else 0
                break
        if anchor_index is None:
            return []

        result = getattr(self, "_ocr_result", None)
        page_width = result.page_dimensions.get(anchor_page, (0, 0))[0] if result else 0
        if not page_width:
            return []
        divider = page_width * 0.5
        collected: list[str] = []
        for line in lines[anchor_index + 1 : anchor_index + 1 + max_lines]:
            if not line or line[0].page != anchor_page:
                break
            selected = [
                word for word in line if (word.x + word.width / 2 < divider) == (side == "left")
            ]
            if not selected:
                continue
            selected.sort(key=lambda word: word.x)
            cleaned = re.sub(r"\s+", " ", " ".join(word.text for word in selected)).strip()
            lowered = cleaned.lower()
            if any(label in lowered for label in stop_labels):
                break
            if cleaned:
                collected.append(cleaned)
        return collected

    @staticmethod
    def _normalize_gstin(value: str) -> str:
        candidate = re.sub(r"[^A-Z0-9]", "", value.upper())
        chars = list(candidate)
        for index in (0, 1, 7, 8, 9, 10, 12):
            if index < len(chars):
                chars[index] = {"O": "0", "I": "1", "L": "1"}.get(chars[index], chars[index])
        return "".join(chars)

    def _extract_amount(
        self,
        text: str,
        words: list[OCRWord],
        context_labels: list[str],
    ) -> FieldValue | None:
        """
        Extract a monetary amount using context labels.

        Collects ALL amounts near each label and returns the LARGEST one.
        This ensures we pick the tax-inclusive grand total (e.g. ₹16,999)
        rather than the net amount (e.g. ₹13,280) which appears first.
        """
        text_lower = text.lower()
        best_amount: float | None = None
        best_raw: str | None = None

        for label in context_labels:
            label_pos = text_lower.find(label)
            if label_pos == -1:
                continue

            # Search for amounts near the label (same line, ±200 chars)
            search_start = max(0, label_pos - 20)
            search_end = min(len(text), label_pos + 200)
            search_region = text[search_start:search_end]

            for pattern in AMOUNT_PATTERNS:
                for match in pattern.finditer(search_region):
                    raw_value = match.group(1).replace(",", "")
                    try:
                        amount = float(raw_value)
                        if amount > 0 and (best_amount is None or amount > best_amount):
                            best_amount = amount
                            best_raw = raw_value
                    except ValueError:
                        continue

        if best_raw is not None:
            return self._field_value(best_raw, 0.8)
        return None

    def _extract_taxes(self, text: str) -> list[TaxDetails]:
        """Extract tax information — type, rate, and amounts."""
        taxes: list[TaxDetails] = []
        text_lower = text.lower()

        # Table rows commonly place the percentage before the tax type, e.g.
        # "28% IGST ₹3,718.53". Capture that exact relationship before using
        # looser document-level fallbacks.
        row_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*%\s*[|:]?\s*(IGST|CGST|SGST|GST|VAT)\s*[|:]?\s*"
            r"[₹$€£%]?\s*([\d,]+(?:\.\d{1,2})?)",
            re.IGNORECASE,
        )
        for match in row_pattern.finditer(text):
            label = match.group(2).upper()
            tax_type = TaxType.CGST_SGST if label in {"CGST", "SGST"} else TaxType(label)
            candidate = TaxDetails(
                tax_type=tax_type,
                rate_percent=Decimal(match.group(1)),
                amount=Decimal(str(self._parse_number(match.group(3)))),
            )
            if candidate not in taxes:
                taxes.append(candidate)
        if taxes:
            return taxes

        label_first_pattern = re.compile(
            r"(IGST|CGST|SGST|GST|VAT)\s*(?:@|:)?\s*"
            r"(\d+(?:\.\d+)?)\s*%\s*[₹$€£]?\s*([\d,]+(?:\.\d{1,2})?)",
            re.IGNORECASE,
        )
        label_first_matches = list(label_first_pattern.finditer(text))
        if label_first_matches:
            labels = {match.group(1).upper() for match in label_first_matches}
            if labels.issubset({"CGST", "SGST"}):
                return [
                    TaxDetails(
                        tax_type=TaxType.CGST_SGST,
                        rate_percent=Decimal(label_first_matches[0].group(2)),
                        amount=sum(
                            (
                                Decimal(str(self._parse_number(match.group(3))))
                                for match in label_first_matches
                            ),
                            Decimal("0"),
                        ),
                    )
                ]
            return [
                TaxDetails(
                    tax_type=TaxType(match.group(1).upper()),
                    rate_percent=Decimal(match.group(2)),
                    amount=Decimal(str(self._parse_number(match.group(3)))),
                )
                for match in label_first_matches
            ]

        # Detect tax type
        if "cgst" in text_lower and "sgst" in text_lower:
            tax_type = TaxType.CGST_SGST
        elif "igst" in text_lower:
            tax_type = TaxType.IGST
        elif "gst" in text_lower:
            tax_type = TaxType.GST
        elif "vat" in text_lower:
            tax_type = TaxType.VAT
        else:
            return taxes

        # Extract tax rate
        rate_match = TAX_RATE_PATTERN.search(text)
        rate = Decimal(rate_match.group(1)) if rate_match else None

        # Extract tax amount
        tax_amount = self._extract_labeled_decimal(
            text, ["cgst", "sgst", "igst", "gst amount", "tax amount", "vat"]
        )

        if tax_amount:
            taxes.append(
                TaxDetails(
                    tax_type=tax_type,
                    rate_percent=rate,
                    amount=tax_amount,
                )
            )

        return taxes

    def _extract_line_items(self, text: str, lines: list[list[OCRWord]]) -> list[LineItem]:
        """
        Extract line items from tabular data in the invoice.

        This is the hardest part of invoice extraction. Uses heuristics
        to detect table rows: lines containing both text and numbers
        that look like qty × price = total patterns.
        """
        items: list[LineItem] = []
        text_lines = text.split("\n")

        # Digital-PDF and high-quality OCR table reconstruction. Descriptions
        # may span several lines; the numeric line is recognized independently.
        money_pattern = re.compile(r"[₹$€£]?\s*([\d,]+\.\d{2})")
        row_start_pattern = re.compile(r"^\s*(?:\d{1,3}\s+\|?|\|)\s*([A-Za-z].{3,})$")
        description_parts: list[str] = []
        for raw_line in text_lines:
            line = re.sub(r"\s+", " ", raw_line).strip()
            if re.match(r"(?i)^TOTAL\s*:", line):
                description_parts = []
                break
            row_start = row_start_pattern.match(line)
            if row_start:
                description_parts = [row_start.group(1).strip()]
                continue
            amounts = [
                Decimal(str(self._parse_number(match.group(1))))
                for match in money_pattern.finditer(line)
            ]
            if description_parts and len(amounts) >= 2:
                first_amount = next(money_pattern.finditer(line))
                quantity_match = re.search(r"\b(\d+(?:\.\d+)?)\b", line[first_amount.end() :])
                quantity = Decimal(quantity_match.group(1)) if quantity_match else Decimal("1")
                unit_price = amounts[0]
                net_amount = amounts[1]
                discount = max(Decimal("0"), quantity * unit_price - net_amount)
                items.append(
                    LineItem(
                        description=" ".join(description_parts),
                        quantity=quantity,
                        unit_price=unit_price,
                        discount=discount,
                        line_total=net_amount,
                        confidence=0.93,
                    )
                )
                description_parts = []
                continue
            if (
                description_parts
                and line
                and not re.match(r"(?i)^(sl\.?|description|unit price|qty|net amount|tax)", line)
            ):
                description_parts.append(line)

        if items:
            return items

        # Pattern for a line item row: description, quantity, unit price, then
        # optional numeric columns. The final amount is always the line total.
        currency_pattern = r"[₹$€£]?\s*"
        line_item_pattern = re.compile(
            r"(.+?)\s+"  # Description
            r"(\d+(?:\.\d+)?)\s+"  # Quantity
            + currency_pattern
            + r"([\d,]+(?:\.\d{1,2})?)"  # Unit price
            + r"((?:\s+"
            + currency_pattern
            + r"[\d,]+(?:\.\d{1,2})?)+)\s*$"  # Remaining numeric columns
        )
        summary_labels = {"total", "subtotal", "sub total", "grand total", "tax total"}

        for line in text_lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue

            match = line_item_pattern.search(line)
            if match:
                try:
                    desc = match.group(1).strip()
                    if desc.lower().rstrip(":") in summary_labels:
                        continue
                    qty = Decimal(match.group(2))
                    unit_price = Decimal(match.group(3).replace(",", ""))
                    trailing_amounts = re.findall(r"[\d,]+(?:\.\d{1,2})?", match.group(4))
                    if not trailing_amounts:
                        continue
                    discount = Decimal("0")
                    line_total = Decimal(trailing_amounts[-1].replace(",", ""))

                    # Sanity check: does qty * unit_price ≈ line_total?
                    expected = qty * unit_price - discount
                    tolerance = abs(float(expected)) * 0.05  # 5% tolerance
                    if abs(float(expected - line_total)) <= max(tolerance, 1.0):
                        confidence = 0.85
                    else:
                        confidence = 0.5

                    items.append(
                        LineItem(
                            description=desc,
                            quantity=qty,
                            unit_price=unit_price,
                            discount=discount,
                            line_total=line_total,
                            confidence=confidence,
                        )
                    )
                except (InvalidOperation, ValueError):
                    continue

        return items

    def _extract_grand_total(self, text: str) -> Decimal | None:
        """Extract the tax-inclusive payable value without confusing net amount."""
        number = r"[₹$€£]?\s*([\d,]+(?:\.\d{1,2})?)"
        for pattern in (
            rf"(?is)invoice\s+value\s*:\s*(?:\n\s*)?{number}",
            rf"(?im)^(?:grand total|amount due|total payable|balance due)\s*:?\s*{number}",
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return Decimal(str(self._parse_number(match.group(1))))

        total_block = re.search(r"(?im)^TOTAL\s*:\s*([^\n]*(?:\n[^\n]+)?)", text)
        if total_block:
            amounts = re.findall(r"[₹$€£]?\s*([\d,]+\.\d{2})", total_block.group(1))
            if amounts:
                return Decimal(str(self._parse_number(amounts[-1])))

        fallback = self._extract_amount(text, [], TOTAL_LABELS)
        return (
            Decimal(str(self._parse_number(fallback.value)))
            if fallback and fallback.value
            else None
        )

    def _extract_labeled_decimal(self, text: str, labels: list[str]) -> Decimal:
        for label in labels:
            pattern = (
                rf"(?im)^\s*{re.escape(label)}\s*:?\s*"
                r"[₹$€£]?\s*([\d,]+(?:\.\d{1,2})?)"
            )
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return Decimal(str(self._parse_number(match.group(1))))
        return Decimal("0")

    def _detect_currency(self, text: str) -> str:
        """Detect currency from symbols or codes in the text."""
        for symbol, currency in CURRENCY_MAP.items():
            if symbol in text:
                return currency
        return "INR"  # Default

    @staticmethod
    def _parse_number(value: str) -> float:
        """Parse US, Indian, and European-formatted monetary values."""
        if not value:
            return 0.0
        cleaned = re.sub(r"[^\d,.\-]", "", value)
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            tail = cleaned.rsplit(",", 1)[1]
            cleaned = cleaned.replace(",", ".") if len(tail) == 2 else cleaned.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _field_value(self, value: str | None, confidence: float) -> FieldValue:
        return FieldValue(
            value=value,
            confidence=confidence,
            source=ExtractionSource.OCR_REGEX,
            bounding_box=self._find_bounding_box(value) if value else None,
        )

    def _find_bounding_box(self, value: str) -> BoundingBox | None:
        """Locate a value in OCR words and normalize its union box for UI overlays."""
        result = getattr(self, "_ocr_result", None)
        if result is None:
            return None
        needles = [part.lower() for part in re.findall(r"[A-Z0-9]+", value, re.IGNORECASE)]
        if not needles:
            return None
        words = result.words
        for start in range(len(words)):
            candidates = words[start : start + len(needles)]
            if len(candidates) != len(needles) or len({w.page for w in candidates}) != 1:
                continue
            normalized = [re.sub(r"[^a-z0-9]", "", w.text.lower()) for w in candidates]
            if normalized != [re.sub(r"[^a-z0-9]", "", n) for n in needles]:
                continue
            page = candidates[0].page
            width, height = result.page_dimensions.get(page, (0, 0))
            if not width or not height:
                return None
            return BoundingBox(
                x0=max(0.0, min(w.x for w in candidates) / width),
                y0=max(0.0, min(w.y for w in candidates) / height),
                x1=min(1.0, max(w.x + w.width for w in candidates) / width),
                y1=min(1.0, max(w.y + w.height for w in candidates) / height),
                page=page,
            )
        return None

    def _extract_labeled_value(self, text: str, patterns: list[str]) -> FieldValue | None:
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self._field_value(match.group(1).strip(), 0.82)
        return None

    @staticmethod
    def _extract_labeled_text(text: str, pattern: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None
