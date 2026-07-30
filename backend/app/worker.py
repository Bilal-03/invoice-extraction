"""Run the durable OCR worker locally: ``python -m app.worker``."""

import asyncio
import socket

from app.api.v1.deps import build_ocr_engine, build_storage, build_vlm_client
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.logging import get_logger, setup_logging
from app.domain.entities import Document
from app.services.job_service import claim_next_job, complete_job, fail_job
from app.tasks.pipeline_tasks import run_extraction_pipeline

setup_logging()
logger = get_logger(__name__)


async def run_worker() -> None:
    settings = get_settings()
    worker_id = f"{socket.gethostname()}-{id(asyncio.current_task())}"
    storage = build_storage(settings)
    ocr_engine = build_ocr_engine(settings)
    vlm_client = build_vlm_client(settings)
    logger.info("worker_started", worker_id=worker_id)

    while True:
        async with async_session_factory() as session:
            job = await claim_next_job(session, worker_id)
            await session.commit()
        if not job:
            await asyncio.sleep(settings.worker_poll_interval_seconds)
            continue

        try:
            await run_extraction_pipeline(job.document_id, storage, ocr_engine, vlm_client)
            async with async_session_factory() as session:
                fresh_job = await session.get(type(job), job.id)
                document = await session.get(Document, job.document_id)
                if document and document.status == "completed":
                    await complete_job(session, fresh_job)
                else:
                    await fail_job(
                        session,
                        fresh_job,
                        RuntimeError(document.error_message if document else "Missing document"),
                    )
                await session.commit()
        except Exception as exc:
            logger.exception("worker_job_failed", job_id=job.id, error=str(exc))
            async with async_session_factory() as session:
                fresh_job = await session.get(type(job), job.id)
                if fresh_job:
                    await fail_job(session, fresh_job, exc)
                    await session.commit()


if __name__ == "__main__":
    asyncio.run(run_worker())
