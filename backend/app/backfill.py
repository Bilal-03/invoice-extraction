"""Idempotently project completed document extractions into AP records.

Run with ``python -m app.backfill`` after deploying the AP migration. Existing
documents remain the evidence record; this command only creates or refreshes
their normalized AP projection.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.database import async_session_factory, init_db
from app.domain.entities import Document
from app.domain.schemas import DocumentStatus
from app.services.ap_service import project_document


async def backfill() -> int:
    await init_db()
    async with async_session_factory() as session:
        documents = list(
            await session.scalars(
                select(Document).where(
                    Document.status == DocumentStatus.COMPLETED.value,
                    Document.extraction_result.is_not(None),
                )
            )
        )
        projected = 0
        for document in documents:
            if await project_document(session, document):
                projected += 1
        await session.commit()
    print(f"Projected {projected} completed documents into AP records")
    return projected


if __name__ == "__main__":
    asyncio.run(backfill())
