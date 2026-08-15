"""Local QR/e-invoice detection and QR-versus-OCR comparison.

The detector deliberately treats the QR payload as evidence, not as a source
that silently replaces OCR or rule-extracted invoice fields. Indian e-invoice
payloads appear as JSON, base64-wrapped JSON, or provider-specific key/value
text, so this module normalises the common field names while keeping the
original payload for review.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from app.domain.schemas import InvoiceExtraction, QRComparisonResult
from app.extraction.gst import normalize_gstin
from app.validation.date_validator import parse_invoice_date

QR_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "invoice_number": (
        "docno",
        "docnumber",
        "invoiceno",
        "invoicenumber",
        "invoiceid",
        "billno",
    ),
    "invoice_date": ("docdt", "docdate", "invoicedate", "invoicedt"),
    "seller_gstin": (
        "sellergstin",
        "suppliergstin",
        "suppliergstinno",
        "suppliergstinnumber",
        "gstin",
    ),
    "buyer_gstin": ("buyergstin", "recipientgstin", "customergstin"),
    "taxable_amount": (
        "tottaxableval",
        "taxablevalue",
        "taxableamount",
        "taxable",
    ),
    "tax_total": ("tottax", "totaltax", "taxamount", "tax"),
    "grand_total": (
        "totinvval",
        "totalinvoicevalue",
        "invoicevalue",
        "grandtotal",
        "totalamount",
        "total",
    ),
    "irn": ("irn",),
    "ack_number": ("ackno", "acknumber", "acknowledgementnumber", "ack"),
}
AMOUNT_FIELDS = {"taxable_amount", "tax_total", "grand_total"}


def _empty_result() -> dict[str, Any]:
    return {
        "qr_detected": False,
        "qr_payload": None,
        "irn": None,
        "ack_number": None,
        "qr_fields": {},
        "page": None,
    }


def detect_qr(image: np.ndarray | None) -> dict[str, Any]:
    """Decode the first QR code found in one image with OpenCV."""

    return detect_qrs([image])


def detect_qrs(images: Iterable[np.ndarray | None]) -> dict[str, Any]:
    """Scan document pages until a usable QR payload is found."""

    best_payload: str | None = None
    best_fields: dict[str, str] = {}
    best_page: int | None = None
    for page, image in enumerate(images, start=1):
        payload = _decode_payload(image)
        if payload:
            fields = _extract_qr_fields(payload)
            if best_payload is None or len(fields) > len(best_fields):
                best_payload = payload
                best_fields = fields
                best_page = page
    if best_payload is not None:
        return {
            "qr_detected": True,
            "qr_payload": best_payload,
            "irn": best_fields.get("irn"),
            "ack_number": best_fields.get("ack_number"),
            "qr_fields": best_fields,
            "page": best_page,
        }
    return _empty_result()


def parse_qr_payload(payload: str) -> dict[str, str]:
    """Extract normalised invoice fields from a decoded QR payload."""

    return _extract_qr_fields(payload)


def compare_qr_with_extraction(
    qr_fields: dict[str, str],
    extraction: InvoiceExtraction,
) -> tuple[str, dict[str, QRComparisonResult]]:
    """Compare fields present in both QR and OCR/rule extraction.

    Returns ``not_comparable`` when the QR exists but contains no field that
    OCR also extracted. Missing OCR values remain missing; they are never
    filled from the QR automatically.
    """

    ocr_fields: dict[str, str | None] = {
        "invoice_number": extraction.invoice_number.value,
        "invoice_date": extraction.invoice_date,
        "seller_gstin": (
            extraction.vendor.gstin.value if extraction.vendor.gstin else None
        ),
        "buyer_gstin": (
            extraction.buyer.gstin.value
            if extraction.buyer and extraction.buyer.gstin
            else None
        ),
        "taxable_amount": (
            str(extraction.subtotal - extraction.discount_total)
            if extraction.subtotal is not None
            else None
        ),
        "tax_total": str(extraction.tax_total) if extraction.tax_total is not None else None,
        "grand_total": str(extraction.grand_total) if extraction.grand_total is not None else None,
    }
    results: dict[str, QRComparisonResult] = {}
    for field, qr_value in qr_fields.items():
        if field not in ocr_fields or field in {"irn", "ack_number"}:
            continue
        if not qr_value:
            continue
        ocr_value = ocr_fields[field]
        if not ocr_value:
            results[field] = QRComparisonResult(
                status="not_comparable",
                ocr_value=None,
                qr_value=qr_value,
                message="QR contains this field but OCR/rules did not extract it",
            )
            continue
        qr_key = _canonical_value(field, qr_value)
        ocr_key = _canonical_value(field, ocr_value)
        matched = qr_key == ocr_key
        difference = None
        if not matched and field in AMOUNT_FIELDS:
            difference = _amount_difference(qr_value, ocr_value)
        results[field] = QRComparisonResult(
            status="match" if matched else "mismatch",
            ocr_value=ocr_value,
            qr_value=qr_value,
            difference=difference,
            message=(
                "QR and OCR values match"
                if matched
                else "QR and OCR values differ; review the source evidence"
            ),
        )

    comparable = [result for result in results.values() if result.status != "not_comparable"]
    if any(result.status == "mismatch" for result in comparable):
        return "mismatch", results
    if any(result.status == "match" for result in comparable):
        return "match", results
    return "not_comparable", results


def _decode_payload(image: np.ndarray | None) -> str | None:
    if image is None or image.size == 0:
        return None
    candidates = [image]
    try:
        if len(image.shape) == 3:
            candidates.append(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    except Exception:
        pass

    detector = cv2.QRCodeDetector()
    payloads: list[str] = []
    for candidate in candidates:
        try:
            found, decoded, _, _ = detector.detectAndDecodeMulti(candidate)
            if found and decoded:
                for payload in decoded:
                    if payload and payload.strip():
                        payloads.append(payload.strip())
        except Exception:
            pass
        try:
            payload, _, _ = detector.detectAndDecode(candidate)
            if payload and payload.strip():
                payloads.append(payload.strip())
        except Exception:
            pass
    if not payloads:
        return None
    return max(payloads, key=lambda payload: len(_extract_qr_fields(payload)))


def _extract_qr_fields(payload: str) -> dict[str, str]:
    data = _payload_mapping(payload)
    if data:
        flattened: dict[str, Any] = {}
        _flatten_mapping(data, flattened)
        fields: dict[str, str] = {}
        for canonical, aliases in QR_FIELD_ALIASES.items():
            for alias in aliases:
                value = flattened.get(_normalise_key(alias))
                if value not in (None, ""):
                    fields[canonical] = str(value)
                    break
        return fields

    # A small fallback for non-JSON QR payloads such as key=value|key=value.
    fields = {}
    for key, value in _key_value_pairs(payload).items():
        normalised_key = _normalise_key(key)
        for canonical, aliases in QR_FIELD_ALIASES.items():
            if normalised_key in aliases:
                fields[canonical] = value
                break
    return fields


def _payload_mapping(payload: str) -> dict[str, Any] | None:
    candidates = [payload]
    encoded = re.sub(r"\s+", "", payload)
    if len(encoded) >= 16:
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
            if decoded and decoded not in candidates:
                candidates.append(decoded)
        except (ValueError, UnicodeDecodeError):
            pass

    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            parsed = parse_qs(urlparse(candidate).query)
            if parsed:
                return {key: values[-1] for key, values in parsed.items() if values}
            continue
        if isinstance(value, dict):
            return value
    return None


def _flatten_mapping(value: dict[str, Any], output: dict[str, Any]) -> None:
    for key, item in value.items():
        output[_normalise_key(str(key))] = item
        if isinstance(item, dict):
            _flatten_mapping(item, output)


def _key_value_pairs(payload: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for part in re.split(r"[|;&,\n]", payload):
        if "=" in part:
            key, value = part.split("=", 1)
        elif ":" in part:
            key, value = part.split(":", 1)
        else:
            continue
        if key.strip() and value.strip():
            pairs[key.strip()] = value.strip()
    return pairs


def _normalise_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _canonical_value(field: str, value: str) -> str:
    if field in AMOUNT_FIELDS:
        try:
            amount = Decimal(re.sub(r"[^0-9.-]", "", value)).quantize(Decimal("0.01"))
            return format(amount, "f")
        except (InvalidOperation, ValueError):
            return re.sub(r"\s+", "", value).casefold()
    if field == "invoice_date":
        parsed = parse_invoice_date(value)
        if parsed is not None:
            return parsed.date().isoformat()
    if field in {"seller_gstin", "buyer_gstin"}:
        return normalize_gstin(value)
    if field == "invoice_number":
        return _normalise_key(value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _amount_difference(first: str, second: str) -> str | None:
    try:
        left = Decimal(re.sub(r"[^0-9.-]", "", first))
        right = Decimal(re.sub(r"[^0-9.-]", "", second))
        return format(abs(left - right).quantize(Decimal("0.01")), "f")
    except (InvalidOperation, ValueError):
        return None
