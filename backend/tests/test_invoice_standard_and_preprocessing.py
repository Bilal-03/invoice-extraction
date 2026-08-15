from decimal import Decimal

import numpy as np

from app.adapters.ocr.base import OCREngine, OCRResult
from app.adapters.ocr.fallback import FallbackOCREngine
from app.adapters.preprocessing.pipeline import PreprocessingPipeline
from app.domain.schemas import (
    BuyerDetails,
    FieldValue,
    InvoiceExtraction,
    LineItem,
    TaxDetails,
    TaxType,
    VendorDetails,
)


def test_extraction_maps_to_the_universal_nested_invoice_standard() -> None:
    extraction = InvoiceExtraction(
        invoice_number=FieldValue(value="INV-42", confidence=0.98),
        invoice_date="2026-08-01",
        due_date="2026-08-31",
        po_reference=FieldValue(value="PO-9", confidence=0.9),
        vendor=VendorDetails(
            name=FieldValue(value="Acme Supplies", confidence=0.95),
            gstin=FieldValue(value="27ABCDE1234F1Z5", confidence=0.9),
            bank_account=FieldValue(value="123456789", confidence=0.8),
        ),
        buyer=BuyerDetails(name=FieldValue(value="Example Buyer", confidence=0.9)),
        line_items=[
            LineItem(
                description="Paper",
                quantity=Decimal("2"),
                unit_price=Decimal("50"),
                line_total=Decimal("100"),
                confidence=0.9,
            )
        ],
        taxes=[TaxDetails(tax_type=TaxType.CGST_SGST, amount=Decimal("18"))],
        subtotal=Decimal("100"),
        tax_total=Decimal("18"),
        grand_total=Decimal("118"),
    )

    standard = extraction.to_standard()

    assert standard.document_type == "tax_invoice"
    assert standard.invoice.invoice_number == "INV-42"
    assert standard.invoice.po_number == "PO-9"
    assert standard.seller.gstin == "27ABCDE1234F1Z5"
    assert standard.buyer.name == "Example Buyer"
    assert standard.items[0].line_total == Decimal("100")
    assert standard.taxes.cgst == Decimal("9")
    assert standard.taxes.sgst == Decimal("9")
    assert standard.totals.grand_total == Decimal("118")
    assert standard.payment.account_number == "123456789"


async def test_preprocessing_runs_resize_contrast_and_threshold_steps() -> None:
    image = np.full((400, 300, 3), 240, dtype=np.uint8)
    result = await PreprocessingPipeline(
        deskew=False,
        denoise=False,
        orient=False,
    ).process(image)

    assert result.original_shape == image.shape
    assert result.image.ndim == 2
    assert any(step.startswith("resize(") for step in result.steps_applied)
    assert "grayscale" in result.steps_applied
    assert "contrast_clahe" in result.steps_applied
    assert "adaptive_threshold" in result.steps_applied


class _FakeOCREngine(OCREngine):
    def __init__(self, engine_name: str, confidence: float):
        self.engine_name = engine_name
        self.confidence = confidence

    @property
    def name(self) -> str:
        return self.engine_name

    async def extract(self, image: np.ndarray) -> OCRResult:
        return OCRResult(
            raw_text=self.engine_name,
            average_confidence=self.confidence,
            engine_name=self.engine_name,
        )


async def test_paddle_primary_falls_back_when_ocr_confidence_is_low() -> None:
    engine = FallbackOCREngine(
        _FakeOCREngine("pp-structure-v3", 0.2),
        _FakeOCREngine("tesseract", 0.9),
    )

    result = await engine.extract(np.zeros((10, 10), dtype=np.uint8))

    assert result.engine_name == "tesseract"
