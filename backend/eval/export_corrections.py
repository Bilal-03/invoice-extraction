"""Export human corrections as a small future-training dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import async_session_factory
from app.domain.entities import AuditEntryModel
from app.services.corrections import training_value


async def export_corrections(output: Path, tenant_id: str | None = None) -> int:
    async with async_session_factory() as session:
        query = select(AuditEntryModel).order_by(AuditEntryModel.timestamp)
        if tenant_id:
            query = query.where(AuditEntryModel.tenant_id == tenant_id)
        entries = list(await session.scalars(query))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for entry in entries:
            stream.write(
                json.dumps(
                    {
                        "id": entry.id,
                        "document_id": entry.document_id,
                        "tenant_id": entry.tenant_id,
                        # Stable aliases for training consumers.  Keep the
                        # legacy names below for backwards compatibility.
                        "field": entry.field_path,
                        "predicted": training_value(entry.old_value),
                        "correct": training_value(entry.new_value),
                        "field_path": entry.field_path,
                        "old_value": entry.old_value,
                        "new_value": entry.new_value,
                        "corrected_by": entry.corrected_by,
                        "timestamp": entry.timestamp.isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"Exported {len(entries)} corrections to {output}")
    return len(entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tenant-id")
    args = parser.parse_args()
    asyncio.run(export_corrections(args.output, args.tenant_id))
