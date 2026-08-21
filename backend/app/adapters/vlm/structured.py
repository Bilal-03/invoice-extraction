"""Shared JSON prompt and response mapping for local vision providers."""

import json
from decimal import Decimal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

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


class LocalVLMLineItem(BaseModel):
    """Pydantic boundary for one model-produced invoice row."""

    model_config = ConfigDict(extra="ignore")

    description: str | None = None
    hsn_sac: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    gst_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    discount: Decimal | None = None
    line_total: Decimal | None = None


class LocalVLMTax(BaseModel):
    """Pydantic boundary for one model-produced tax row."""

    model_config = ConfigDict(extra="ignore")

    tax_type: TaxType = TaxType.NONE
    rate_percent: Decimal | None = None
    amount: Decimal | None = None


class LocalVLMResponse(BaseModel):
    """Provider-neutral JSON contract enforced before application mapping."""

    model_config = ConfigDict(extra="ignore")

    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    po_reference: str | None = None
    payment_terms: str | None = None
    place_of_supply: str | None = None
    vendor_name: str | None = None
    vendor_address: str | None = None
    vendor_gstin: str | None = None
    vendor_pan: str | None = None
    buyer_name: str | None = None
    buyer_billing_address: str | None = None
    buyer_shipping_address: str | None = None
    buyer_gstin: str | None = None
    buyer_pan: str | None = None
    line_items: list[LocalVLMLineItem] = Field(default_factory=list)
    taxes: list[LocalVLMTax] = Field(default_factory=list)
    subtotal: Decimal | None = None
    discount_total: Decimal | None = None
    tax_total: Decimal | None = None
    shipping_amount: Decimal | None = None
    grand_total: Decimal | None = None
    currency: str | None = None
    field_locations: dict[str, BoundingBox] = Field(default_factory=dict)


PROMPT = """You are a local invoice extraction engine.
Extract only information visibly supported by the invoice image. Never invent values.
Return JSON only matching the supplied shape. Use null for missing scalar and numeric
values, and [] when there is no item table. Never convert an uncertain value to zero.
Dates should preserve the printed format. Monetary values must be numbers without symbols.
Use this shape:
{
  "invoice_number": null, "invoice_date": null, "due_date": null,
  "po_reference": null, "payment_terms": null, "place_of_supply": null,
  "vendor_name": null, "vendor_address": null, "vendor_gstin": null, "vendor_pan": null,
  "buyer_name": null, "buyer_billing_address": null, "buyer_shipping_address": null,
  "buyer_gstin": null, "buyer_pan": null,
  "line_items": [{"description":null, "hsn_sac":null, "quantity":null,
                  "unit_price":null, "gst_rate":null, "tax_amount":null,
                  "discount":null, "line_total":null}],
  "taxes": [{"tax_type":"CGST_SGST", "rate_percent":null, "amount":null}],
  "subtotal": null, "discount_total": null, "tax_total": null, "shipping_amount": null,
  "grand_total": null, "currency": "INR",
  "field_locations": {}
}
"""


def image_b64(image: np.ndarray) -> str:
    """Encode an invoice image for an OpenAI-compatible vision endpoint."""
    success, encoded = cv2.imencode(".jpg", image)
    if not success:
        raise ValueError("Unable to encode invoice image for local VLM")
    import base64

    return base64.b64encode(encoded.tobytes()).decode("ascii")


def prompt_for(existing_extraction: InvoiceExtraction | None = None) -> str:
    """Give the model untrusted deterministic candidates to verify against the image."""
    if existing_extraction is None:
        return PROMPT
    candidate = existing_extraction.model_dump(
        mode="json",
        exclude={
            "standardized_invoice",
            "document_structure",
            "field_locations",
            "processing_time_ms",
            "vlm_input_tokens",
            "vlm_output_tokens",
            "estimated_cost_usd",
        },
    )
    return (
        f"{PROMPT}\nThese are untrusted OCR/rule candidates. Verify every value against "
        "the image; correct only when the image provides evidence:\n"
        f"{json.dumps(candidate, separators=(',', ':'))}"
    )


def parse_json_response(raw: str) -> dict:
    """Parse JSON returned by local servers that may wrap it in Markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").removeprefix("json").removesuffix("```").strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Local VLM response must be a JSON object")
    return parsed


def validate_response(data: dict) -> LocalVLMResponse:
    """Validate the provider response before any values enter the domain model."""

    return LocalVLMResponse.model_validate(data)


def map_to_extraction(data: dict) -> InvoiceExtraction:
    """Validate and map provider-neutral JSON into the application contract."""
    payload = validate_response(data)
    locations = payload.field_locations

    def location(name: str) -> BoundingBox | None:
        return locations.get(name)

    def field(value, name: str) -> FieldValue:
        return FieldValue(
            value=str(value) if value not in (None, "") else None,
            confidence=0.82 if value not in (None, "") else 0.0,
            source=ExtractionSource.LOCAL_VLM,
            bounding_box=location(name),
        )

    line_items = []
    for item in payload.line_items:
        observed = sum(
            value is not None
            for value in (
                item.description,
                item.hsn_sac,
                item.quantity,
                item.unit_price,
                item.gst_rate,
                item.tax_amount,
                item.discount,
                item.line_total,
            )
        )
        line_items.append(
            LineItem(
                description=item.description or "",
                hsn_sac=item.hsn_sac,
                quantity=item.quantity or 0,
                unit_price=item.unit_price or 0,
                gst_rate=item.gst_rate,
                tax_amount=item.tax_amount or 0,
                discount=item.discount or 0,
                line_total=item.line_total or 0,
                confidence=min(0.82, 0.35 + observed * 0.06),
            )
        )
    taxes = []
    for tax in payload.taxes:
        taxes.append(
            TaxDetails(
                tax_type=tax.tax_type,
                rate_percent=tax.rate_percent,
                amount=tax.amount or 0,
            )
        )
    buyer_values = (
        payload.buyer_name,
        payload.buyer_billing_address,
        payload.buyer_shipping_address,
        payload.buyer_gstin,
        payload.buyer_pan,
    )
    extraction = InvoiceExtraction(
        invoice_number=field(payload.invoice_number, "invoice_number"),
        invoice_date=payload.invoice_date,
        due_date=payload.due_date,
        po_reference=field(payload.po_reference, "po_reference"),
        payment_terms=payload.payment_terms,
        place_of_supply=payload.place_of_supply,
        vendor=VendorDetails(
            name=field(payload.vendor_name, "vendor_name"),
            address=field(payload.vendor_address, "vendor_address"),
            gstin=field(payload.vendor_gstin, "vendor_gstin"),
            pan=field(payload.vendor_pan, "vendor_pan"),
        ),
        buyer=(
            BuyerDetails(
                name=field(payload.buyer_name, "buyer_name"),
                billing_address=field(payload.buyer_billing_address, "buyer_billing_address"),
                shipping_address=field(payload.buyer_shipping_address, "buyer_shipping_address"),
                gstin=field(payload.buyer_gstin, "buyer_gstin"),
                pan=field(payload.buyer_pan, "buyer_pan"),
            )
            if any(value not in (None, "") for value in buyer_values)
            else None
        ),
        line_items=line_items,
        taxes=taxes,
        subtotal=payload.subtotal,
        discount_total=payload.discount_total or 0,
        tax_total=(
            payload.tax_total if payload.tax_total is not None else sum(tax.amount for tax in taxes)
        ),
        shipping_amount=payload.shipping_amount or 0,
        grand_total=payload.grand_total,
        currency=payload.currency or "INR",
        overall_confidence=0.82,
        extraction_source=ExtractionSource.LOCAL_VLM,
        field_locations={key: box for key, box in locations.items() if location(key) is not None},
    )
    extraction.ensure_standardized()
    return extraction


def token_count(value: object) -> int:
    """Convert optional provider token counters into a stable integer."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def zero_cost() -> Decimal:
    return Decimal("0")
