"""
Google Gemini VLM client implementation.

Uses the Gemini API with structured output mode to extract invoice
fields from images. Returns Pydantic-validated JSON directly —
no second regex pass on the VLM's text output.
"""

import base64
import json
from decimal import Decimal
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

from app.adapters.vlm.base import VLMClient
from app.core.config import get_settings
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

logger = get_logger(__name__)


def _image_to_base64(image: np.ndarray) -> str:
    """Convert an OpenCV image to a base64-encoded JPEG string."""
    # Convert BGR to RGB
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if len(image.shape) == 3 else image

    pil_image = Image.fromarray(image_rgb)

    # Resize if too large (Gemini has size limits)
    max_dim = 2048
    if max(pil_image.size) > max_dim:
        ratio = max_dim / max(pil_image.size)
        new_size = (int(pil_image.width * ratio), int(pil_image.height * ratio))
        pil_image = pil_image.resize(new_size, Image.LANCZOS)

    buffer = BytesIO()
    pil_image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# The structured prompt for Gemini
_EXTRACTION_PROMPT = """You are an expert invoice data extractor. Analyze this invoice image and
extract ALL fields into the following JSON structure.

Be precise and extract exactly what you see. For fields you cannot find, use null.
For monetary values, use numbers only (no currency symbols).
For dates, use the format shown on the invoice.

Return ONLY valid JSON with this exact structure:
{
  "invoice_number": "string or null",
  "invoice_date": "string or null",
  "due_date": "string or null",
  "po_reference": "string or null",
  "payment_terms": "string or null",
  "vendor_name": "string or null",
  "vendor_address": "string or null",
  "vendor_gstin": "string or null",
  "buyer_name": "string or null",
  "buyer_billing_address": "string or null",
  "buyer_shipping_address": "string or null",
  "line_items": [
    {
      "description": "string",
      "quantity": number,
      "unit_price": number,
      "discount": number,
      "line_total": number
    }
  ],
  "tax_type": "GST|CGST_SGST|IGST|VAT|NONE",
  "tax_rate": number or null,
  "tax_amount": number or null,
  "subtotal": number or null,
  "discount_total": number or null,
  "tax_total": number or null,
  "shipping_amount": number or null,
  "grand_total": number or null,
  "currency": "INR|USD|EUR|GBP",
  "field_locations": {
    "invoice_number": {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0, "page": 0}
  }
}
For every non-null scalar field, include an approximate normalized bounding box
in field_locations when you can locate it. Coordinates are fractions of the
page from top-left; use page 0 for the first page. Never invent a box for a
field that is not present.

Line-item rules: inspect the invoice's table visually, not just the OCR text.
Return one object for every visible product or service row, including rows
whose description wraps across multiple lines and rows such as shipping
charges. Map the table columns to description, quantity, unit_price, discount,
and line_total. Use numeric values from the image, remove currency symbols and
thousands separators, and return [] only when there is genuinely no item table.
Do not omit a row because OCR merged its columns or misread a character."""


class GeminiVLMClient(VLMClient):
    """
    Google Gemini Vision Language Model client.

    Uses structured prompting to independently verify invoice fields while
    OCR/layout extraction runs in parallel.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.settings = settings
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.vlm_model

        if not self.api_key:
            raise ValueError("Gemini API key not configured. Set GEMINI_API_KEY env var.")

        logger.info("gemini_client_initialized", model=self.model)

    @property
    def name(self) -> str:
        return f"gemini/{self.model}"

    async def extract_fields(
        self,
        image: np.ndarray,
        existing_extraction: InvoiceExtraction | None = None,
    ) -> InvoiceExtraction:
        """Extract invoice fields using Gemini Vision."""
        import httpx

        image_b64 = _image_to_base64(image)

        prompt = _EXTRACTION_PROMPT
        if existing_extraction and existing_extraction.invoice_number.value:
            prompt += (
                f"\n\nPartial extraction already done (fill in missing fields): "
                f"Invoice #{existing_extraction.invoice_number.value}"
            )

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_b64,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {"maxOutputTokens": 2048, "response_mime_type": "application/json"},
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url, json=payload, headers={"x-goog-api-key": self.api_key}
            )
            response.raise_for_status()

        result = response.json()

        # Parse Gemini response
        try:
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            # Clean up potential markdown wrapping
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0]
            data = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error("gemini_parse_error", error=str(e), raw=str(result)[:500])
            raise ValueError(f"Failed to parse Gemini response: {e}") from e

        # Convert raw JSON to InvoiceExtraction
        extraction = self._map_to_extraction(data)
        usage = result.get("usageMetadata", {})
        extraction.vlm_input_tokens = int(usage.get("promptTokenCount", 0))
        extraction.vlm_output_tokens = int(usage.get("candidatesTokenCount", 0))
        estimated_cost = (
            extraction.vlm_input_tokens * self.settings.vlm_input_cost_per_million
            + extraction.vlm_output_tokens * self.settings.vlm_output_cost_per_million
        ) / 1_000_000
        extraction.estimated_cost_usd = Decimal(str(estimated_cost))

        logger.info(
            "gemini_extraction_complete",
            invoice_number=extraction.invoice_number.value,
            fields_extracted=sum(
                1
                for f in [
                    extraction.invoice_number.value,
                    extraction.invoice_date,
                    extraction.due_date,
                    extraction.vendor.name.value,
                    extraction.grand_total,
                ]
                if f is not None
            ),
        )

        return extraction

    def _map_to_extraction(self, data: dict) -> InvoiceExtraction:
        """Map Gemini's raw JSON response to our InvoiceExtraction schema."""
        source = ExtractionSource.VLM_FALLBACK

        locations = data.get("field_locations") or {}

        def _location(name: str) -> BoundingBox | None:
            raw = locations.get(name)
            if not raw:
                return None
            try:
                return BoundingBox.model_validate(raw)
            except Exception:
                logger.warning("gemini_invalid_field_location", field=name)
                return None

        def _field(value, name: str) -> FieldValue:
            return FieldValue(
                value=str(value) if value is not None else None,
                confidence=0.85 if value is not None else 0.0,
                source=source,
                bounding_box=_location(name),
            )

        # Parse line items
        line_items = []
        for item in data.get("line_items", []):
            line_items.append(
                LineItem(
                    description=str(item.get("description", "")),
                    quantity=item.get("quantity", 0),
                    unit_price=item.get("unit_price", 0),
                    discount=item.get("discount", 0),
                    line_total=item.get("line_total", 0),
                    confidence=0.8,
                )
            )

        # Parse tax details
        taxes = []
        tax_amount = data.get("tax_amount")
        if tax_amount is not None:
            tax_type_str = data.get("tax_type", "NONE")
            try:
                tax_type = TaxType(tax_type_str)
            except ValueError:
                tax_type = TaxType.NONE

            taxes.append(
                TaxDetails(
                    tax_type=tax_type,
                    rate_percent=data.get("tax_rate"),
                    amount=tax_amount,
                )
            )

        return InvoiceExtraction(
            invoice_number=_field(data.get("invoice_number"), "invoice_number"),
            invoice_date=data.get("invoice_date"),
            due_date=data.get("due_date"),
            po_reference=_field(data.get("po_reference"), "po_reference"),
            payment_terms=data.get("payment_terms"),
            vendor=VendorDetails(
                name=_field(data.get("vendor_name"), "vendor_name"),
                address=_field(data.get("vendor_address"), "vendor_address"),
                gstin=_field(data.get("vendor_gstin"), "vendor_gstin"),
            ),
            buyer=BuyerDetails(
                name=_field(data.get("buyer_name"), "buyer_name"),
                billing_address=_field(data.get("buyer_billing_address"), "buyer_billing_address"),
                shipping_address=_field(
                    data.get("buyer_shipping_address"), "buyer_shipping_address"
                ),
            )
            if any(
                data.get(key)
                for key in (
                    "buyer_name",
                    "buyer_billing_address",
                    "buyer_shipping_address",
                )
            )
            else None,
            line_items=line_items,
            taxes=taxes,
            subtotal=data.get("subtotal"),
            discount_total=data.get("discount_total") or 0,
            tax_total=data.get("tax_total") or sum(tax.amount for tax in taxes),
            shipping_amount=data.get("shipping_amount") or 0,
            grand_total=data.get("grand_total"),
            currency=data.get("currency", "INR"),
            overall_confidence=0.85,
            extraction_source=source,
            field_locations={
                key: location
                for key in (
                    "invoice_date",
                    "due_date",
                    "payment_terms",
                    "subtotal",
                    "tax_total",
                    "grand_total",
                    "currency",
                )
                if (location := _location(key)) is not None
            },
        )

    async def health_check(self) -> bool:
        """Verify Gemini API is reachable."""
        try:
            import httpx

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers={"x-goog-api-key": self.api_key})
                return response.status_code == 200
        except Exception as e:
            logger.error("gemini_health_fail", error=str(e))
            return False
