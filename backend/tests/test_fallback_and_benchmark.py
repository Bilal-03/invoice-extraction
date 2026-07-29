from decimal import Decimal

import numpy as np
import pytest

from app.adapters.ocr.base import OCREngine, OCRResult
from app.adapters.ocr.fallback import FallbackOCREngine
from eval.run_benchmark import score_records


class StubOCR(OCREngine):
    def __init__(self, confidence: float, text: str):
        self.confidence = confidence
        self.text = text

    @property
    def name(self) -> str:
        return self.text

    async def extract(self, image: np.ndarray) -> OCRResult:
        return OCRResult(raw_text=self.text, average_confidence=self.confidence)


@pytest.mark.asyncio
async def test_low_confidence_ocr_uses_fallback():
    engine = FallbackOCREngine(StubOCR(0.1, "primary"), StubOCR(0.9, "fallback"))
    result = await engine.extract(np.zeros((8, 8), dtype=np.uint8))
    assert result.raw_text == "fallback"


def test_benchmark_metrics_include_exact_match_and_ocr_ablation():
    expected = {
        "invoice_number": {"value": "INV-1"},
        "invoice_date": "2026-01-01",
        "due_date": "2026-02-01",
        "vendor": {"name": {"value": "Acme"}},
        "grand_total": Decimal("10.00"),
        "currency": "USD",
        "line_items": [
            {
                "description": "Item",
                "quantity": 1,
                "unit_price": 10,
                "discount": 0,
                "line_total": 10,
            }
        ],
    }
    predicted = {**expected, "processing_time_ms": 100, "extraction_source": "ocr_regex"}
    metrics = score_records(
        [
            {
                "expected": expected,
                "predicted": predicted,
                "expected_ocr_text": "Invoice one",
                "predicted_ocr_text_before": "Invoice xne",
                "predicted_ocr_text": "Invoice one",
            }
        ]
    )
    assert metrics["exact_match_accuracy"] == 1.0
    assert metrics["line_items"]["cell_accuracy"] == 1.0
    assert metrics["ocr"]["after"]["cer"] == 0.0
    assert metrics["ocr"]["before"]["cer"] > 0
