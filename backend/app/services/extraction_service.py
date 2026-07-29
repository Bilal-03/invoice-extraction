"""
Extraction Service — Orchestrates the full pipeline.

This service ties all the adapters together:
  Image -> Preprocessing -> OCR -> Regex Extraction -> Validation
                               -> (Optional VLM Fallback) -> Final Validation

Demonstrates dependency injection: it takes the OCR engine and VLM client
as dependencies, rather than instantiating them directly.
"""

import time
from collections.abc import Awaitable, Callable

import numpy as np

from app.adapters.layout.base import LayoutExtractor
from app.adapters.layout.spatial import SpatialLayoutExtractor
from app.adapters.ocr.base import OCREngine, OCRResult
from app.adapters.preprocessing.pipeline import PreprocessingPipeline
from app.adapters.vlm.base import VLMClient
from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.schemas import DocumentStatus, ExtractionSource, FieldValue, InvoiceExtraction
from app.services.validation_service import ValidationService

logger = get_logger(__name__)


class ExtractionService:
    """Orchestrates the document extraction pipeline."""

    def __init__(
        self,
        ocr_engine: OCREngine,
        vlm_client: VLMClient | None = None,
        layout_extractor: LayoutExtractor | None = None,
    ):
        self.settings = get_settings()
        self.ocr_engine = ocr_engine
        self.vlm_client = vlm_client
        self.preprocessing = PreprocessingPipeline(
            deskew=self.settings.preprocessing_deskew,
            denoise=self.settings.preprocessing_denoise,
            orient=self.settings.preprocessing_orient,
        )
        self.layout_extractor = layout_extractor or SpatialLayoutExtractor()
        self.validator = ValidationService()

    async def extract_from_image(self, image: np.ndarray) -> InvoiceExtraction:
        """Run the full extraction pipeline on an image."""
        return await self.extract_from_images([image])

    async def extract_from_images(
        self,
        images: list[np.ndarray],
        status_callback: Callable[[DocumentStatus], Awaitable[None]] | None = None,
        *,
        text_hint: str | None = None,
    ) -> InvoiceExtraction:
        """Run one extraction over all pages, retaining per-page OCR coordinates."""
        if not images:
            raise ValueError("At least one page image is required")
        start_time = time.time()

        try:

            async def report(status: DocumentStatus) -> None:
                if status_callback:
                    await status_callback(status)

            # 1. Preprocess every page
            logger.info("pipeline_stage", stage="preprocessing")
            await report(DocumentStatus.PREPROCESSING)
            processed_pages = []
            for image in images:
                prep_result = await self.preprocessing.process(image)
                processed_pages.append(prep_result.image)

            # 2. OCR every page and combine results without destroying layout metadata
            logger.info("pipeline_stage", stage="ocr", engine=self.ocr_engine.name)
            await report(DocumentStatus.OCR)
            page_results = []
            for page_index, processed_image in enumerate(processed_pages):
                result = await self.ocr_engine.extract(processed_image)
                for word in result.words:
                    word.page = page_index
                result.page_dimensions[page_index] = (
                    int(processed_image.shape[1]),
                    int(processed_image.shape[0]),
                )
                page_results.append(result)
            ocr_result = self._combine_ocr_results(page_results)
            if text_hint:
                ocr_result.raw_text = text_hint
                ocr_result.engine_name = f"{ocr_result.engine_name}+pdf_text"
            self.last_ocr_result = ocr_result

            # 3. Primary Extraction (Regex + Spatial)
            logger.info("pipeline_stage", stage="primary_extraction")
            await report(DocumentStatus.EXTRACTING)
            extraction = self.layout_extractor.extract(ocr_result)

            # 4. First pass validation
            logger.info("pipeline_stage", stage="validation_pass_1")
            await report(DocumentStatus.VALIDATING)
            extraction.validation_flags = self.validator.validate(extraction)
            extraction.overall_confidence = self._composite_confidence(
                extraction, ocr_result.average_confidence
            )

            # 5. VLM Fallback (Confidence-gated)
            if self._should_trigger_vlm(extraction):
                logger.info(
                    "pipeline_stage",
                    stage="vlm_fallback",
                    reason="low_confidence_or_missing_fields",
                )
                try:
                    # Pass the *original* image to the VLM, not the preprocessed one
                    # VLMs prefer color and original context
                    vlm_extraction = await self.vlm_client.extract_fields(
                        images[0], existing_extraction=extraction
                    )

                    # Merge results (VLM wins on missing/low-confidence fields)
                    extraction = self._merge_extractions(extraction, vlm_extraction)

                    # Re-validate after VLM
                    extraction.validation_flags = self.validator.validate(extraction)
                    extraction.overall_confidence = self._composite_confidence(
                        extraction, ocr_result.average_confidence
                    )
                except Exception as e:
                    logger.error("vlm_fallback_failed", error=str(e))
                    # Continue with the original extraction if VLM fails

            # 6. Finalize
            extraction.processing_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "pipeline_complete",
                processing_time_ms=extraction.processing_time_ms,
                overall_confidence=extraction.overall_confidence,
                source=extraction.extraction_source.value,
            )

            return extraction

        except Exception as e:
            logger.exception("pipeline_failed", error=str(e))
            raise

    @staticmethod
    def _combine_ocr_results(results: list[OCRResult]) -> OCRResult:
        words = [word for result in results for word in result.words]
        confidences = [word.confidence for word in words if word.confidence >= 0]
        dimensions: dict[int, tuple[int, int]] = {}
        for result in results:
            dimensions.update(result.page_dimensions)
        return OCRResult(
            raw_text="\n\f\n".join(result.raw_text for result in results),
            words=words,
            average_confidence=(sum(confidences) / len(confidences)) if confidences else 0.0,
            engine_name=results[0].engine_name if results else "unknown",
            page_count=len(results),
            page_dimensions=dimensions,
        )

    def _should_trigger_vlm(self, extraction: InvoiceExtraction) -> bool:
        """Decide if VLM fallback is needed based on confidence and required fields."""
        if not self.settings.vlm_enabled or not self.vlm_client:
            return False

        # Check overall confidence against threshold
        if extraction.overall_confidence < self.settings.vlm_confidence_threshold:
            return True

        # Check if critical fields are missing
        if not extraction.invoice_number.value or not extraction.vendor.name.value:
            return True

        # Check if validation failed completely
        error_flags = [f for f in extraction.validation_flags if f.severity == "error"]
        return bool(error_flags)

    def _merge_extractions(
        self, primary: InvoiceExtraction, fallback: InvoiceExtraction
    ) -> InvoiceExtraction:
        """
        Merge fallback results into the primary extraction.
        Fallback values win only if the primary value is missing or very low confidence.
        """
        merged = primary.model_copy(deep=True)

        def choose(current: FieldValue | None, candidate: FieldValue | None) -> FieldValue | None:
            if candidate is None or candidate.value in (None, ""):
                return current
            if (
                current is None
                or current.value in (None, "")
                or candidate.confidence > current.confidence
            ):
                return candidate
            return current

        merged.invoice_number = (
            choose(primary.invoice_number, fallback.invoice_number) or primary.invoice_number
        )
        merged.po_reference = choose(primary.po_reference, fallback.po_reference)
        merged.vendor.name = (
            choose(primary.vendor.name, fallback.vendor.name) or primary.vendor.name
        )
        merged.vendor.address = choose(primary.vendor.address, fallback.vendor.address)
        merged.vendor.gstin = choose(primary.vendor.gstin, fallback.vendor.gstin)
        merged.vendor.bank_account = choose(
            primary.vendor.bank_account, fallback.vendor.bank_account
        )
        if primary.buyer and fallback.buyer:
            merged.buyer.name = choose(primary.buyer.name, fallback.buyer.name)
            merged.buyer.billing_address = choose(
                primary.buyer.billing_address, fallback.buyer.billing_address
            )
            merged.buyer.shipping_address = choose(
                primary.buyer.shipping_address, fallback.buyer.shipping_address
            )
        for scalar in (
            "invoice_date",
            "due_date",
            "payment_terms",
            "buyer",
            "subtotal",
            "discount_total",
            "tax_total",
            "shipping_amount",
            "grand_total",
        ):
            current_value = getattr(merged, scalar)
            if current_value in (None, "", []) or (
                scalar in {"discount_total", "tax_total", "shipping_amount"} and not current_value
            ):
                setattr(merged, scalar, getattr(fallback, scalar))
        if not merged.line_items and fallback.line_items:
            merged.line_items = fallback.line_items
        if not merged.taxes and fallback.taxes:
            merged.taxes = fallback.taxes
        if fallback.currency and merged.currency == "INR":
            merged.currency = fallback.currency
        merged.overall_confidence = round(
            max(primary.overall_confidence, fallback.overall_confidence), 3
        )
        merged.vlm_input_tokens = fallback.vlm_input_tokens
        merged.vlm_output_tokens = fallback.vlm_output_tokens
        merged.estimated_cost_usd = fallback.estimated_cost_usd
        merged.extraction_source = ExtractionSource.VLM_FALLBACK
        logger.info("merge_strategy", strategy="field_confidence_merge")
        return merged

    @staticmethod
    def _composite_confidence(extraction: InvoiceExtraction, ocr_confidence: float) -> float:
        flags = extraction.validation_flags
        validation_rate = sum(1 for flag in flags if flag.passed) / len(flags) if flags else 0.5
        return round(
            min(
                1.0,
                0.6 * extraction.overall_confidence + 0.2 * ocr_confidence + 0.2 * validation_rate,
            ),
            3,
        )
