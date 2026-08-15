import numpy as np
import pytest
from pydantic import ValidationError

from app.adapters.vlm.llama_cpp_client import LlamaCppVLMClient
from app.adapters.vlm.ollama_client import OllamaVLMClient
from app.adapters.vlm.structured import image_b64, map_to_extraction, prompt_for
from app.domain.schemas import FieldValue, InvoiceExtraction, VendorDetails
from app.services.extraction_service import ExtractionService


def test_local_vlm_provider_names_are_explicit() -> None:
    assert OllamaVLMClient("http://ollama", "qwen3-vl:2b").name == "ollama/qwen3-vl:2b"
    assert LlamaCppVLMClient("http://llama", "invoice-model").name == "llama.cpp/invoice-model"


def test_provider_neutral_json_maps_to_invoice_contract() -> None:
    extraction = map_to_extraction(
        {
            "invoice_number": "INV-LOCAL",
            "vendor_name": "Example Vendor",
            "buyer_name": "Example Buyer",
            "buyer_gstin": "27BUYER1234F1Z5",
            "buyer_pan": "PQRSX5678K",
            "grand_total": 118,
            "line_items": [],
            "taxes": [],
        }
    )

    assert extraction.invoice_number.value == "INV-LOCAL"
    assert extraction.vendor.name.value == "Example Vendor"
    assert extraction.buyer is not None
    assert extraction.buyer.gstin.value == "27BUYER1234F1Z5"
    assert extraction.buyer.pan.value == "PQRSX5678K"
    assert extraction.grand_total == 118
    assert extraction.standardized_invoice is not None


def test_local_vlm_null_numeric_values_are_safe_and_pydantic_validated() -> None:
    extraction = map_to_extraction(
        {
            "invoice_number": None,
            "vendor_name": "Example Vendor",
            "line_items": [
                {
                    "description": "Uncertain service",
                    "quantity": None,
                    "unit_price": None,
                    "line_total": None,
                }
            ],
            "taxes": [{"tax_type": "CGST_SGST", "amount": None}],
        }
    )

    assert extraction.line_items[0].quantity == 0
    assert extraction.line_items[0].unit_price == 0
    assert extraction.line_items[0].confidence < 0.5
    assert extraction.taxes[0].amount == 0

    with pytest.raises(ValidationError):
        map_to_extraction({"line_items": "not-a-list"})


def test_prompt_marks_deterministic_values_as_untrusted_candidates() -> None:
    prompt = prompt_for(
        InvoiceExtraction(
            invoice_number=FieldValue(value="INV-1", confidence=0.9),
            vendor=VendorDetails(name=FieldValue(value="Vendor", confidence=0.9)),
        )
    )

    assert "untrusted OCR/rule candidates" in prompt
    assert "INV-1" in prompt
    assert "Never convert an uncertain value to zero" in prompt


def test_vlm_is_only_requested_for_unreliable_deterministic_results() -> None:
    service = ExtractionService(ocr_engine=object())
    reliable = InvoiceExtraction(
        invoice_number=FieldValue(value="INV-1", confidence=0.9),
        vendor=VendorDetails(name=FieldValue(value="Vendor", confidence=0.9)),
        grand_total=118,
        overall_confidence=0.95,
    )
    unreliable = reliable.model_copy(update={"overall_confidence": 0.4})
    missing = reliable.model_copy(update={"invoice_number": FieldValue(value=None)})

    assert service._needs_verification(reliable) is False
    assert service._needs_verification(unreliable) is True
    assert service._needs_verification(missing) is True


def test_local_vlm_image_payload_can_be_created() -> None:
    payload = image_b64(np.zeros((8, 8, 3), dtype=np.uint8))
    assert payload
