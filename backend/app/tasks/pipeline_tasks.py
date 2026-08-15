"""Extraction pipeline executed exclusively by the durable worker."""

import asyncio

import cv2
from sqlalchemy import delete, select

from app.adapters.ocr.base import OCREngine
from app.adapters.parsing.base import DocumentParser
from app.adapters.storage.base import ObjectStorage
from app.adapters.tables.digital import extract_pdf_tables
from app.adapters.vlm.base import VLMClient
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.metrics import record_document
from app.core.tracing import stage_span
from app.domain.entities import AIRun, Document, DocumentPreprocessingArtifact, OCRToken
from app.domain.schemas import DocumentStatus, ValidationFlag, ValidationSeverity
from app.services.ap_service import project_document
from app.services.extraction_service import ExtractionService
from app.services.job_service import add_event
from app.services.qr_service import compare_qr_with_extraction, detect_qrs

logger = get_logger(__name__)
_pipeline_slots = asyncio.Semaphore(get_settings().pipeline_max_concurrency)


def _merge_document_structures(
    current: dict | None,
    incoming: dict | None,
) -> dict | None:
    """Keep parser metadata from multiple local table/layout providers."""

    if not current:
        return incoming
    if not incoming:
        return current
    merged = dict(current)
    for key, value in incoming.items():
        if key == "tables" and isinstance(value, list):
            existing = merged.get("tables") if isinstance(merged.get("tables"), list) else []
            merged["tables"] = existing + value
        elif key == "parser" and merged.get("parser"):
            merged["parsers"] = [merged["parser"], value]
        else:
            merged[key] = value
    return merged


async def _persist_preprocessing_artifacts(
    session,
    storage: ObjectStorage,
    document: Document,
    results,
) -> None:
    """Store one processed PNG and its transform metadata for every page."""

    previous = list(
        await session.scalars(
            select(DocumentPreprocessingArtifact).where(
                DocumentPreprocessingArtifact.document_id == document.id
            )
        )
    )
    for artifact in previous:
        try:
            await storage.delete(artifact.processed_file_path)
        except Exception as exc:
            logger.warning(
                "preprocessed_artifact_cleanup_failed",
                document_id=document.id,
                key=artifact.processed_file_path,
                error=str(exc),
            )
    await session.execute(
        delete(DocumentPreprocessingArtifact).where(
            DocumentPreprocessingArtifact.document_id == document.id
        )
    )

    for page, result in enumerate(results):
        success, encoded = cv2.imencode(".png", result.image)
        if not success:
            raise ValueError(f"Could not encode processed page {page + 1}")
        processed_key = f"{document.id}/processed/page-{page + 1:03d}.png"
        await storage.upload(encoded.tobytes(), processed_key)
        session.add(
            DocumentPreprocessingArtifact(
                document_id=document.id,
                tenant_id=document.tenant_id,
                page=page,
                original_file_path=document.file_path,
                processed_file_path=processed_key,
                original_width=int(result.original_shape[1]),
                original_height=int(result.original_shape[0]),
                processed_width=int(result.image.shape[1]),
                processed_height=int(result.image.shape[0]),
                steps_applied=result.steps_applied,
                deskew_angle=result.deskew_angle,
                orientation_correction=result.orientation_correction,
                estimated_dpi=result.estimated_dpi,
            )
        )


async def run_extraction_pipeline(
    document_id: str,
    storage: ObjectStorage,
    ocr_engine: OCREngine,
    vlm_client: VLMClient | None = None,
    document_parser: DocumentParser | None = None,
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
            await _run_extraction_pipeline(
                document_id, storage, ocr_engine, vlm_client, document_parser
            )


async def _run_extraction_pipeline(
    document_id: str,
    storage: ObjectStorage,
    ocr_engine: OCREngine,
    vlm_client: VLMClient | None = None,
    document_parser: DocumentParser | None = None,
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
                # Keep a rendered page set even for digital PDFs. Native text
                # coordinates remain the extraction source, while the page
                # images give review and preprocessing an identical evidence
                # path for every input type.
                images = load_pdf_pages(file_bytes)
                text_hint = None
                if not images:
                    raise ValueError("PDF has no pages")
                document.page_count = len(images)
                digital_tables = extract_pdf_tables(file_bytes)
                document_structure = (
                    {"parser": "digital-table-adapters", "tables": digital_tables}
                    if digital_tables
                    else None
                )
            else:
                images = [load_image_from_bytes(file_bytes)]
                text_hint = None
                native_ocr = None
                document_structure = None

            if document_parser is not None:
                try:
                    parsed = await document_parser.parse_bytes(
                        file_bytes, document.original_filename or document.filename
                    )
                    document_structure = _merge_document_structures(
                        document_structure, parsed.structure
                    )
                    if parsed.page_count:
                        document.page_count = parsed.page_count
                    if parsed.text and native_ocr is not None:
                        # Keep PyMuPDF's native coordinates while allowing
                        # Docling's reading order/table structure to drive rules.
                        native_ocr.raw_text = parsed.text
                        native_ocr.structured_data = document_structure
                    elif parsed.text:
                        text_hint = parsed.text
                except Exception as exc:
                    logger.warning("document_parser_failed_using_pymupdf_path", error=str(exc))

            if not native_ocr:
                document.page_count = len(images)

            first_page_image = load_pdf_page(file_bytes, 0) if is_pdf else images[0]

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

            if native_ocr:
                await service.preprocess_images(images)
                verification_image = first_page_image if settings.vlm_enabled else None
                extraction_result = await service.extract_from_ocr_result(
                    native_ocr,
                    update_status,
                    verification_image=verification_image,
                    document_structure=document_structure,
                )
            else:
                extraction_result = await service.extract_from_images(
                    images,
                    update_status,
                    text_hint=text_hint,
                    document_structure=document_structure,
                )

            await _persist_preprocessing_artifacts(
                session,
                storage,
                document,
                service.last_preprocessing_results,
            )

            qr_details = detect_qrs(images)
            extraction_result.einvoice.qr_detected = bool(qr_details["qr_detected"])
            extraction_result.einvoice.qr_payload = qr_details["qr_payload"]  # type: ignore[assignment]
            extraction_result.einvoice.irn = qr_details["irn"]  # type: ignore[assignment]
            extraction_result.einvoice.ack_number = qr_details["ack_number"]  # type: ignore[assignment]
            extraction_result.einvoice.qr_fields = qr_details.get("qr_fields", {})
            comparison_status, comparison_results = compare_qr_with_extraction(
                extraction_result.einvoice.qr_fields,
                extraction_result,
            )
            extraction_result.einvoice.comparison_status = comparison_status
            extraction_result.einvoice.comparison_results = comparison_results
            if extraction_result.einvoice.qr_detected:
                extraction_result.validation_flags.append(
                    ValidationFlag(
                        rule="qr_detected",
                        passed=True,
                        message=(
                            "Invoice QR code detected locally"
                            f" on page {qr_details.get('page') or 1}"
                        ),
                        severity=ValidationSeverity.INFO,
                        details={
                            "page": qr_details.get("page"),
                            "fields": qr_details.get("qr_fields", {}),
                        },
                    )
                )
                if comparison_status == "mismatch":
                    extraction_result.validation_flags.append(
                        ValidationFlag(
                            rule="qr_ocr_mismatch",
                            passed=False,
                            message="QR-derived invoice data does not match OCR/rule extraction",
                            severity=ValidationSeverity.WARNING,
                            details={
                                "comparison_status": comparison_status,
                                "comparisons": {
                                    key: result.model_dump(mode="json")
                                    for key, result in comparison_results.items()
                                },
                            },
                        )
                    )
                elif comparison_status == "match":
                    extraction_result.validation_flags.append(
                        ValidationFlag(
                            rule="qr_ocr_match",
                            passed=True,
                            message="QR-derived invoice data matches OCR/rule extraction",
                            severity=ValidationSeverity.INFO,
                            details={
                                "comparison_status": comparison_status,
                                "comparisons": {
                                    key: result.model_dump(mode="json")
                                    for key, result in comparison_results.items()
                                },
                            },
                        )
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

            # QR detection and duplicate validation are part of the final
            # evidence pass, so refresh the universal shape after them too.
            extraction_result.ensure_standardized()

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

            ocr_result_for_storage = native_ocr or getattr(service, "last_ocr_result", None)
            if ocr_result_for_storage is not None:
                document.ocr_text = ocr_result_for_storage.raw_text
                await session.execute(delete(OCRToken).where(OCRToken.document_id == document.id))
                for word in ocr_result_for_storage.words:
                    page_width, page_height = ocr_result_for_storage.page_dimensions.get(
                        word.page, (0, 0)
                    )
                    session.add(
                        OCRToken(
                            document_id=document.id,
                            tenant_id=document.tenant_id,
                            page=word.page,
                            text=word.text,
                            confidence=word.confidence,
                            x=word.x,
                            y=word.y,
                            width=word.width,
                            height=word.height,
                            page_width=page_width,
                            page_height=page_height,
                        )
                    )

            # Promote the extraction into the normalized AP domain in the
            # same transaction so every completed document is immediately
            # searchable, reviewable, and available to the dashboard.
            ap_invoice = await project_document(session, document)
            if vlm_client is not None and (
                extraction_result.vlm_input_tokens or extraction_result.vlm_output_tokens
            ):
                session.add(
                    AIRun(
                        document_id=document.id,
                        invoice_id=ap_invoice.id if ap_invoice else None,
                        provider=vlm_client.name.split("/", 1)[0],
                        model=vlm_client.name.split("/", 1)[1]
                        if "/" in vlm_client.name
                        else vlm_client.name,
                        selected=extraction_result.extraction_source
                        in {"vlm_fallback", "local_vlm"},
                        input_tokens=extraction_result.vlm_input_tokens,
                        output_tokens=extraction_result.vlm_output_tokens,
                        estimated_cost_usd=extraction_result.estimated_cost_usd,
                    )
                )

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
