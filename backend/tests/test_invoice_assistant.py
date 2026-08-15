from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.adapters.vlm.ollama_client import invoice_assistant_prompt
from app.domain.schemas import InvoiceQuestionResponse
from app.services.invoice_assistant import answer_invoice_question


def _bundle():
    invoice = SimpleNamespace(
        id="invoice-1",
        document_id="document-1",
        invoice_number="INV-2026-1",
        invoice_date=date(2026, 8, 15),
        due_date=date(2026, 9, 15),
        po_number=None,
        currency="INR",
        subtotal=Decimal("50000"),
        tax_total=Decimal("9000"),
        grand_total=Decimal("59000"),
        outstanding_amount=Decimal("59000"),
        status="review_required",
        risk_score=10,
        risk_level="low",
        match_status="not_applicable",
        match_details={},
    )
    return {
        "invoice": invoice,
        "document": None,
        "vendor": SimpleNamespace(name="ABC Technologies", gstin="27ABCDE1234F1Z5"),
        "items": [SimpleNamespace(description="Laptop")],
        "taxes": [
            SimpleNamespace(tax_type="CGST", amount=Decimal("4500")),
            SimpleNamespace(tax_type="SGST", amount=Decimal("4500")),
        ],
        "validations": [
            SimpleNamespace(
                passed=False,
                message="Total mismatch. Difference: ₹2,000",
                rule="arithmetic",
                severity="error",
                details={},
            )
        ],
        "risks": [
            SimpleNamespace(
                message="Arithmetic mismatch",
                points=10,
                code="arithmetic",
                level="low",
                details={},
            )
        ],
    }


def test_assistant_prompt_is_grounded_in_invoice_json_and_ocr():
    prompt = invoice_assistant_prompt(
        "What is the payment due date?",
        {"invoice": {"due_date": "2026-09-15"}},
        "Due Date: 15 September 2026",
    )

    assert "INVOICE JSON" in prompt
    assert "OCR TEXT" in prompt
    assert "Do not invent" in prompt
    assert '"evidence"' in prompt


@pytest.mark.asyncio
async def test_deterministic_fallback_answers_common_ap_questions():
    bundle = _bundle()

    due = await answer_invoice_question("What is the payment due date?", bundle, "")
    assert due.answer == "2026-09-15"
    assert due.provider == "deterministic-rules"

    taxes = await answer_invoice_question("What are the GST charges?", bundle, "")
    assert "CGST: ₹4,500.00" in taxes.answer
    assert "SGST: ₹4,500.00" in taxes.answer

    suspicious = await answer_invoice_question("Is there anything suspicious?", bundle, "")
    assert "Arithmetic mismatch" in suspicious.answer
    assert "invoice.risk_flags" in suspicious.evidence


class _FakeOllama:
    name = "ollama/qwen3-vl:2b"

    def __init__(self):
        self.received: tuple[str, dict, str] | None = None

    async def health_check(self) -> bool:
        return True

    async def answer_question(self, question: str, invoice_json: dict, ocr_text: str):
        self.received = (question, invoice_json, ocr_text)
        return InvoiceQuestionResponse(
            question=question,
            answer="15 September 2026",
            evidence=["invoice.due_date"],
            provider=self.name,
            grounded=True,
        )


@pytest.mark.asyncio
async def test_local_assistant_receives_invoice_json_and_ocr_context():
    client = _FakeOllama()
    response = await answer_invoice_question(
        "What is the payment due date?",
        _bundle(),
        "Due Date: 15 September 2026",
        assistant_client=client,
    )

    assert response.provider == "ollama/qwen3-vl:2b"
    assert response.grounded is True
    assert client.received is not None
    assert client.received[1]["invoice"]["due_date"] == "2026-09-15"
    assert "Due Date" in client.received[2]
