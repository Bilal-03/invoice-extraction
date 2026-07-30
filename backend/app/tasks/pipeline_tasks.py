"""Extraction pipeline executed exclusively by the durable worker."""

import asyncio

from sqlalchemy import select

from app.adapters.ocr.base import OCREngine
from app.adapters.storage.base import ObjectStorage
from app.adapters.vlm.base import VLMClient
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.metrics import record_document
from app.core.tracing import stage_span
from app.domain.entities import Document
from app.domain.schemas import DocumentStatus, ValidationFlag, ValidationSeverity
from app.services.extraction_service import ExtractionService
from app.services.job_service import add_event

logger = get_logger(__name__)
_pipeline_slots = asyncio.Semaphore(get_settings().pipeline_max_concurrency)


async def run_extraction_pipeline(
    document_id: str,
    storage: ObjectStorage,
    ocr_engine: OCREngine,
    vlm_client: VLMClient | None = None,
) -> None:
    """
    Run the full extraction pipeline after a durable job has been claimed.

    1. Fetch document from DB
    2. Download image bytes from storage
    3. Run ExtractionService
    4. Save results back to DB
    """
    with stage_span("invoice.pipeline", document_id=document_id):
        async with _pipeline_slots:
            await _run_extraction_pipeline(document_id, storage, ocr_engine, vlm_client)


async def _run_extraction_pipeline(
    document_id: str,
    storage: ObjectStorage,
    ocr_engine: OCREngine,
    vlm_client: VLMClient | None = None,
) -> None:
    """Process one job after acquiring a bounded local worker slot."""
    settings = get_settings()
    logger.info("pipeline_started", document_id=document_id)

    async with async_session_factory() as session:
        # Fetch document
        stmt = select(Document).where(Document.id == document_id)
        result = await session.execute(stmt)
        document = result.scalar_one_or_none()

        if not document:
            logger.error("pipeline_aborted_doc_not_found", document_id=document_id)
            return

        try:
            # Update status
            document.status = DocumentStatus.PREPROCESSING.value
            await session.commit()

            # Fetch image bytes
            with stage_span("invoice.storage_download", storage_key=document.file_path):
                file_bytes = await storage.download(document.file_path)

            # Decode every page so multi-page invoices remain one logical document.
            from app.adapters.preprocessing.pipeline import (
                extract_pdf_ocr_result,
                load_image_from_bytes,
                load_pdf_page,
                load_pdf_pages,
            )

            # Detect PDF by magic bytes (%PDF) or file extension
            is_pdf = file_bytes[:4] == b"%PDF" or document.file_path.lower().endswith(".pdf")

            if is_pdf:
                native_ocr = extract_pdf_ocr_result(file_bytes)
                images = []
                text_hint = None
                if native_ocr:
                    document.page_count = native_ocr.page_count
                else:
                    images = load_pdf_pages(file_bytes)
                    if not images:
                        raise ValueError("PDF has no pages")
            else:
                images = [load_image_from_bytes(file_bytes)]
                text_hint = None
                native_ocr = None

            if not native_ocr:
                document.page_count = len(images)

            # Run extraction
            document.status = DocumentStatus.EXTRACTING.value
            await session.commit()

            service = ExtractionService(ocr_engine=ocr_engine, vlm_client=vlm_client)

            async def update_status(pipeline_status: DocumentStatus) -> None:
                document.status = pipeline_status.value
                await add_event(
                    session,
                    document.id,
                    pipeline_status.value,
                    "stage_changed",
                    tenant_id=document.tenant_id,
                    stage=pipeline_status.value,
                )
                await session.commit()

            extraction_result = (
                await service.extract_from_ocr_result(
                    native_ocr,
                    update_status,
                    verification_image=load_pdf_page(file_bytes, 0) if settings.vlm_enabled else None,
                )
                if native_ocr
                else await service.extract_from_images(images, update_status, text_hint=text_hint)
            )

            # Business-key duplicate detection catches re-scans whose bytes differ.
            vendor_name = extraction_result.vendor.name.value
            invoice_number = extraction_result.invoice_number.value
            if vendor_name and invoice_number:
                candidates = await session.scalars(
                    select(Document).where(
                        Document.id != document_id,
                        Document.tenant_id == document.tenant_id,
                        Document.vendor_name == vendor_name,
                        Document.status == DocumentStatus.COMPLETED.value,
                    )
                )
                for candidate in candidates:
                    previous = candidate.extraction_result or {}
                    previous_number = (previous.get("invoice_number") or {}).get("value")
                    if previous_number and previous_number.casefold() == invoice_number.casefold():
                        extraction_result.validation_flags.append(
                            ValidationFlag(
                                rule="duplicate_invoice",
                                passed=False,
                                message=f"Possible duplicate of document {candidate.id}",
                                severity=ValidationSeverity.ERROR,
                            )
                        )
                        break

            # Save results
            with stage_span("invoice.persist_extraction", document_id=document.id):
                document.extraction_result = extraction_result.model_dump(mode="json")
                document.overall_confidence = extraction_result.overall_confidence
                document.processing_time_ms = extraction_result.processing_time_ms
                document.extraction_source = extraction_result.extraction_source.value

            # Denormalise key fields for dashboard filtering/analytics
            if extraction_result.vendor.name.value:
                document.vendor_name = extraction_result.vendor.name.value

            if extraction_result.grand_total is not None:
                document.grand_total = float(extraction_result.grand_total)

            document.currency = extraction_result.currency
            document.status = DocumentStatus.COMPLETED.value

            await add_event(
                session,
                document.id,
                DocumentStatus.COMPLETED.value,
                "extraction_completed",
                tenant_id=document.tenant_id,
            )

            await session.commit()
            record_document(
                "completed",
                extraction_result.extraction_source.value,
                extraction_result.processing_time_ms / 1000,
            )
            logger.info("pipeline_completed_successfully", document_id=document_id)

        except Exception as e:
            # Handle failure
            logger.exception("pipeline_failed", document_id=document_id, error=str(e))

            # Use a fresh session for the error update in case the previous one is broken
            async with async_session_factory() as error_session:
                stmt = select(Document).where(Document.id == document_id)
                res = await error_session.execute(stmt)
                doc = res.scalar_one_or_none()
                if doc:
                    doc.status = DocumentStatus.FAILED.value
                    doc.error_message = str(e)
                    await add_event(
                        error_session,
                        doc.id,
                        DocumentStatus.FAILED.value,
                        "extraction_failed",
                        tenant_id=doc.tenant_id,
                        message=str(e),
                    )
                    await error_session.commit()
            record_document("failed")
