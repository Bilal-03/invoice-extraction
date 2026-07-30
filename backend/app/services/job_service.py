"""Durable queue and event helpers backed by Postgres/SQLite for local development."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import DocumentEvent, DocumentJob


async def add_event(
    session: AsyncSession,
    document_id: str,
    status: str,
    event_type: str,
    *,
    tenant_id: str = "local",
    stage: str | None = None,
    message: str | None = None,
    metadata: dict | None = None,
) -> None:
    session.add(
        DocumentEvent(
            document_id=document_id,
            tenant_id=tenant_id,
            status=status,
            event_type=event_type,
            stage=stage,
            message=message,
            metadata_json=metadata,
        )
    )


async def enqueue_document(
    session: AsyncSession, document_id: str, *, tenant_id: str = "local", max_attempts: int = 3
) -> DocumentJob:
    job = DocumentJob(document_id=document_id, tenant_id=tenant_id, max_attempts=max_attempts)
    session.add(job)
    await add_event(session, document_id, "pending", "queued", tenant_id=tenant_id)
    return job


async def claim_next_job(session: AsyncSession, worker_id: str) -> DocumentJob | None:
    now = datetime.now(UTC)
    # A Render restart can interrupt OCR halfway through. Release abandoned
    # leases so the embedded worker resumes work after the next service wakeup.
    await session.execute(
        update(DocumentJob)
        .where(
            DocumentJob.status == "processing",
            DocumentJob.locked_at.is_not(None),
            DocumentJob.locked_at < now - timedelta(minutes=15),
        )
        .values(status="retrying", locked_at=None, locked_by=None, available_at=now)
    )
    statement = (
        select(DocumentJob)
        .where(DocumentJob.status.in_(["queued", "retrying"]), DocumentJob.available_at <= now)
        .order_by(DocumentJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = await session.scalar(statement)
    if not job:
        return None
    job.status = "processing"
    job.attempt_count += 1
    job.locked_at = now
    job.locked_by = worker_id
    await add_event(
        session, job.document_id, "preprocessing", "processing_started", tenant_id=job.tenant_id
    )
    return job


async def complete_job(session: AsyncSession, job: DocumentJob) -> None:
    job.status = "completed"
    job.completed_at = datetime.now(UTC)
    await add_event(session, job.document_id, "completed", "completed", tenant_id=job.tenant_id)


async def fail_job(session: AsyncSession, job: DocumentJob, error: Exception) -> None:
    job.last_error = str(error)
    job.locked_at = None
    job.locked_by = None
    if job.attempt_count >= job.max_attempts:
        job.status = "dead_letter"
        await add_event(
            session,
            job.document_id,
            "failed",
            "dead_letter",
            tenant_id=job.tenant_id,
            message=str(error),
        )
        return
    job.status = "retrying"
    job.available_at = datetime.now(UTC) + timedelta(seconds=min(60, 2**job.attempt_count))
    await add_event(
        session,
        job.document_id,
        "pending",
        "retry_scheduled",
        tenant_id=job.tenant_id,
        message=str(error),
    )
