"""Keep the conventional architecture import paths stable."""

from app.database import Base
from app.models import Invoice, Vendor
from app.schemas import InvoiceDataStandard, InvoiceStatus, RiskLevel
from app.services.ai import LlamaCppVLMClient, OllamaVLMClient
from app.services.duplicate import duplicate_fingerprint
from app.services.extraction import ExtractionService
from app.services.ocr import PaddleOCREngine, TesseractOCR
from app.services.preprocessing import PreprocessingPipeline
from app.services.validation import ValidationService


def test_backend_feature_boundaries_reexport_single_implementations():
    """The requested tree is a stable facade, not a second model stack."""

    assert Invoice.__tablename__ == "invoices"
    assert Vendor.__tablename__ == "vendors"
    assert "invoices" in Base.metadata.tables
    assert InvoiceDataStandard.__name__ == "InvoiceDataStandard"
    assert InvoiceStatus.REVIEW_REQUIRED.value == "review_required"
    assert RiskLevel.HIGH.value == "high"
    assert PaddleOCREngine.__name__ == "PaddleStructureV3OCREngine"
    assert TesseractOCR.__name__ == "TesseractOCR"
    assert PreprocessingPipeline.__name__ == "PreprocessingPipeline"
    assert ExtractionService.__name__ == "ExtractionService"
    assert ValidationService.__name__ == "ValidationService"
    assert duplicate_fingerprint.__module__ == "app.validation.duplicate_validator"
    assert OllamaVLMClient.__name__ == "OllamaVLMClient"
    assert LlamaCppVLMClient.__name__ == "LlamaCppVLMClient"
