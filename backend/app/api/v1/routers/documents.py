"""
Document endpoints.

Handles upload, status polling, fetching extraction results,
and human correction audit trails.
"""

import asyncio
import copy
import json
import math
from datetime import UTC, date, datetime, time
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.ocr.base import OCREngine
from app.adapters.storage.base import ObjectStorage
from app.adapters.vlm.base import VLMClient
from app.api.v1 import deps
from app.core.config import Settings, get_settings
from app.core.database import async_session_factory, get_db_session
from app.core.logging import get_logger
from app.core.security import get_tenant_id, verify_auth
from app.core.uploads import validate_upload
from app.domain.entities import AuditEntryModel, Document, DocumentEvent, DocumentJob
from app.domain.schemas import (
    AuditEntry,
    BatchUploadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatus,
    DocumentUploadResponse,
    FieldCorrectionRequest,
    InvoiceExtraction,
)
from app.services.job_service import enqueue_document
from app.services.validation_service import ValidationService

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Depends(verify_auth)])


async def _document_response(doc: Document, storage: ObjectStorage) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        status=DocumentStatus(doc.status),
        file_size_bytes=doc.file_size_bytes,
        page_count=doc.page_count,
        error_message=doc.error_message,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        processing_time_ms=doc.processing_time_ms,
        extraction=InvoiceExtraction.model_validate(doc.extraction_result)
        if doc.extraction_result
        else None,
        file_url=await storage.get_url(doc.file_path) if doc.file_path else None,
        preview_url=f"/api/v1/documents/{doc.id}/preview" if doc.file_path else None,
    )


async def _accept_upload(
    file: UploadFile,
    db: AsyncSession,
    storage: ObjectStorage,
    settings: Settings,
    tenant_id: str,
) -> tuple[DocumentUploadResponse, Document | None]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    file_bytes = await file.read()
    mime_type, document_hash = await validate_upload(file.filename, file_bytes, settings)

    duplicate = await db.scalar(
        select(Document)
        .where(Document.document_hash == document_hash, Document.tenant_id == tenant_id)
        .order_by(desc(Document.created_at))
        .limit(1)
    )
    if duplicate:
        return (
            DocumentUploadResponse(
                document_id=duplicate.id,
                status=DocumentStatus(duplicate.status),
                message="Duplicate upload matched an existing document",
                duplicate_of=duplicate.id,
            ),
            None,
        )

    extension = Path(file.filename).suffix.lower()
    doc = Document(
        filename=Path(file.filename).name[:255],
        original_filename=Path(file.filename).name[:255],
        status=DocumentStatus.PENDING.value,
        mime_type=mime_type,
        file_path="",
        file_size_bytes=len(file_bytes),
        document_hash=document_hash,
        tenant_id=tenant_id,
    )
    db.add(doc)
    await db.flush()
    doc.file_path = f"{doc.id}{extension}"
    try:
        await storage.upload(file_bytes, doc.file_path)
        await db.commit()
    except Exception:
        await db.rollback()
        await storage.delete(doc.file_path)
        raise
    return DocumentUploadResponse(document_id=doc.id, status=DocumentStatus.PENDING), doc


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(deps.get_storage),
    ocr_engine: OCREngine = Depends(deps.get_ocr_engine),
    vlm_client: VLMClient | None = Depends(deps.get_vlm_client),
    settings: Settings = Depends(get_settings),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Upload an invoice image or PDF for processing.

    Returns 202 Accepted immediately. Processing happens in the background.
    """
    response, doc = await _accept_upload(file, db, storage, settings, tenant_id)
    if doc:
        logger.info("document_uploaded", document_id=doc.id, filename=doc.filename)
        await enqueue_document(
            db, doc.id, tenant_id=tenant_id, max_attempts=settings.worker_max_attempts
        )
        await db.commit()
    return response


@router.post("/batch", response_model=BatchUploadResponse, status_code=202)
async def upload_document_batch(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(deps.get_storage),
    ocr_engine: OCREngine = Depends(deps.get_ocr_engine),
    vlm_client: VLMClient | None = Depends(deps.get_vlm_client),
    settings: Settings = Depends(get_settings),
    tenant_id: str = Depends(get_tenant_id),
):
    if not files or len(files) > 25:
        raise HTTPException(status_code=400, detail="Upload between 1 and 25 documents")
    responses = []
    for file in files:
        response, doc = await _accept_upload(file, db, storage, settings, tenant_id)
        responses.append(response)
        if doc:
            await enqueue_document(
                db, doc.id, tenant_id=tenant_id, max_attempts=settings.worker_max_attempts
            )
    await db.commit()
    return BatchUploadResponse(documents=responses, accepted=len(responses))


@router.get("/{document_id}/preview")
async def get_document_preview(
    document_id: str,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(deps.get_storage),
    tenant_id: str = Depends(get_tenant_id),
):
    """Render a browser-safe PNG preview for an image or individual PDF page."""
    document = await db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    file_bytes = await storage.download(document.file_path)
    from app.adapters.preprocessing.pipeline import load_image_from_bytes, load_pdf_page

    is_pdf = file_bytes.startswith(b"%PDF") or document.file_path.lower().endswith(".pdf")
    try:
        image = load_pdf_page(file_bytes, page - 1) if is_pdf else load_image_from_bytes(file_bytes)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="Preview page not found") from exc
    import cv2

    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise HTTPException(status_code=422, detail="Could not render document preview")
    return Response(content=encoded.tobytes(), media_type="image/png")


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    vendor: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(deps.get_storage),
    tenant_id: str = Depends(get_tenant_id),
):
    """List documents with pagination and filtering."""
    stmt = select(Document).where(Document.tenant_id == tenant_id)

    if status:
        if status not in {value.value for value in DocumentStatus}:
            raise HTTPException(status_code=400, detail="Unknown document status")
        stmt = stmt.where(Document.status == status)
    if vendor:
        stmt = stmt.where(Document.vendor_name.ilike(f"%{vendor}%"))
    if date_from:
        stmt = stmt.where(Document.created_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to:
        stmt = stmt.where(Document.created_at <= datetime.combine(date_to, time.max, tzinfo=UTC))

    # Count total
    from sqlalchemy import func

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = await db.scalar(count_stmt) or 0

    # Pagination
    stmt = stmt.order_by(desc(Document.created_at))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(stmt)
    docs = result.scalars().all()

    return DocumentListResponse(
        documents=[await _document_response(d, storage) for d in docs],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 0,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(deps.get_storage),
    tenant_id: str = Depends(get_tenant_id),
):
    """Get a specific document by ID, including its extraction results."""
    stmt = select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return await _document_response(doc, storage)


@router.patch("/{document_id}/fields", response_model=DocumentResponse)
async def correct_field(
    document_id: str,
    request: FieldCorrectionRequest,
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(deps.get_storage),
    actor: str | None = Depends(verify_auth),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Human correction endpoint.

    Updates a specific field in the extraction result and writes
    an audit trail entry. This is a crucial feature for enterprise IDP.
    """
    stmt = select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if not doc or not doc.extraction_result:
        raise HTTPException(status_code=404, detail="Document or extraction not found")

    allowed_paths = {
        "invoice_number.value",
        "invoice_date",
        "due_date",
        "po_reference.value",
        "payment_terms",
        "vendor.name.value",
        "vendor.address.value",
        "vendor.gstin.value",
        "vendor.bank_account.value",
        "buyer.name.value",
        "buyer.billing_address.value",
        "buyer.shipping_address.value",
        "subtotal",
        "discount_total",
        "tax_total",
        "shipping_amount",
        "grand_total",
        "currency",
    }
    if request.field_path not in allowed_paths:
        raise HTTPException(status_code=400, detail=f"Field is not editable: {request.field_path}")

    parts = request.field_path.split(".")
    extraction = copy.deepcopy(doc.extraction_result)
    current = extraction
    for part in parts[:-1]:
        if part not in current or current[part] is None:
            current[part] = {"value": None, "confidence": 0.0, "source": "ocr_regex"}
        current = current[part]
    last_part = parts[-1]
    server_old_value = current.get(last_part)
    current[last_part] = request.new_value
    if last_part == "value":
        current["source"] = "human_corrected"
        current["confidence"] = 1.0
    try:
        validated = InvoiceExtraction.model_validate(extraction)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid corrected value: {exc}") from exc
    validated.validation_flags = ValidationService().validate(validated)
    doc.extraction_result = validated.model_dump(mode="json")
    doc.overall_confidence = validated.overall_confidence
    doc.vendor_name = validated.vendor.name.value
    doc.grand_total = float(validated.grand_total) if validated.grand_total is not None else None
    doc.currency = validated.currency

    # Create audit entry
    audit = AuditEntryModel(
        document_id=document_id,
        tenant_id=tenant_id,
        field_path=request.field_path,
        old_value=None if server_old_value is None else str(server_old_value),
        new_value=request.new_value,
        corrected_by=actor or request.corrected_by,
    )
    db.add(audit)

    await db.commit()
    logger.info("field_corrected", document_id=document_id, field=request.field_path)

    return await _document_response(doc, storage)


@router.get("/{document_id}/audit", response_model=list[AuditEntry])
async def get_document_audit_trail(
    document_id: str,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Get the human correction history for a document."""
    stmt = (
        select(AuditEntryModel)
        .where(AuditEntryModel.document_id == document_id, AuditEntryModel.tenant_id == tenant_id)
        .order_by(desc(AuditEntryModel.timestamp))
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    return [
        AuditEntry(
            id=e.id,
            document_id=e.document_id,
            field_path=e.field_path,
            old_value=e.old_value,
            new_value=e.new_value,
            corrected_by=e.corrected_by,
            timestamp=e.timestamp,
        )
        for e in entries
    ]


@router.get("/{document_id}/events")
async def stream_document_status(document_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Stream scoped document status changes to the review UI over SSE."""

    async def event_stream():
        previous = None
        for _ in range(300):
            async with async_session_factory() as session:
                doc = await session.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id))
                if not doc:
                    yield 'event: error\ndata: {"detail":"Document not found"}\n\n'
                    return
                payload = {
                    "document_id": doc.id,
                    "status": doc.status,
                    "updated_at": doc.updated_at.isoformat(),
                    "error_message": doc.error_message,
                }
                serialized = json.dumps(payload)
                if serialized != previous:
                    yield f"data: {serialized}\n\n"
                    previous = serialized
                if doc.status in {DocumentStatus.COMPLETED.value, DocumentStatus.FAILED.value}:
                    return
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{document_id}/events/history")
async def get_document_events(
    document_id: str,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return the durable job timeline used by the dashboard and support tooling."""
    rows = await db.scalars(
        select(DocumentEvent)
        .where(DocumentEvent.document_id == document_id, DocumentEvent.tenant_id == tenant_id)
        .order_by(DocumentEvent.created_at)
    )
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "status": event.status,
            "stage": event.stage,
            "message": event.message,
            "created_at": event.created_at,
        }
        for event in rows
    ]


@router.post("/{document_id}/reprocess", response_model=DocumentUploadResponse, status_code=202)
async def reprocess_document(
    document_id: str,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    tenant_id: str = Depends(get_tenant_id),
):
    """Queue a new attempt without discarding the prior extraction or audit trail."""
    document = await db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id))
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    active_job = await db.scalar(
        select(DocumentJob).where(
            DocumentJob.document_id == document_id,
            DocumentJob.status.in_(["queued", "retrying", "processing"]),
        )
    )
    if active_job:
        raise HTTPException(status_code=409, detail="Document already has an active job")
    document.status = DocumentStatus.PENDING.value
    document.error_message = None
    await enqueue_document(
        db, document_id, tenant_id=document.tenant_id, max_attempts=settings.worker_max_attempts
    )
    await db.commit()
    return DocumentUploadResponse(document_id=document_id, status=DocumentStatus.PENDING)


@router.get("/file/{storage_key}")
async def get_document_file(
    storage_key: str,
    db: AsyncSession = Depends(get_db_session),
    storage: ObjectStorage = Depends(deps.get_storage),
    tenant_id: str = Depends(get_tenant_id),
):
    """Serve the raw uploaded file. Needed for the frontend preview."""
    owner = await db.scalar(select(Document).where(Document.file_path == storage_key, Document.tenant_id == tenant_id))
    if not owner:
        raise HTTPException(status_code=404, detail="File not found")
    if hasattr(storage, "base_dir"):
        try:
            path = storage._resolve_path(storage_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid storage key") from exc
        if path.exists():
            return FileResponse(path)
    elif await storage.exists(storage_key):
        return RedirectResponse(await storage.get_url(storage_key))
    raise HTTPException(status_code=404, detail="File not found")
