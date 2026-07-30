"""
Analytics Service — Data aggregation and reporting.

Translates raw document rows into business metrics.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import Document
from app.domain.schemas import (
    AnalyticsSummary,
    DocumentStatus,
    VendorAnalytics,
    VolumePoint,
)


class AnalyticsService:
    """Service for generating dashboard analytics."""

    def __init__(self, session: AsyncSession, tenant_id: str = "local"):
        self.session = session
        self.tenant_id = tenant_id

    async def get_summary(self) -> AnalyticsSummary:
        """Get high-level platform metrics."""

        # Basic counts
        scope = Document.tenant_id == self.tenant_id
        stmt = select(func.count(Document.id)).where(scope)
        total = await self.session.scalar(stmt) or 0

        stmt = select(func.count(Document.id)).where(
            scope, Document.status == DocumentStatus.COMPLETED.value
        )
        completed = await self.session.scalar(stmt) or 0

        stmt = select(func.count(Document.id)).where(scope, Document.status == DocumentStatus.FAILED.value)
        failed = await self.session.scalar(stmt) or 0

        # Averages (only for completed documents)
        stmt_avg_conf = select(func.avg(Document.overall_confidence)).where(
            scope, Document.status == DocumentStatus.COMPLETED.value
        )
        avg_conf = await self.session.scalar(stmt_avg_conf) or 0.0

        stmt_avg_time = select(func.avg(Document.processing_time_ms)).where(
            scope, Document.status == DocumentStatus.COMPLETED.value
        )
        avg_time = await self.session.scalar(stmt_avg_time) or 0.0

        # VLM Fallback rate
        stmt_vlm = select(func.count(Document.id)).where(
            scope, Document.extraction_source == "vlm_fallback",
            Document.status == DocumentStatus.COMPLETED.value,
        )
        vlm_count = await self.session.scalar(stmt_vlm) or 0
        vlm_rate = (vlm_count / completed) if completed > 0 else 0.0

        # Time-based metrics
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())

        stmt_today = select(func.count(Document.id)).where(scope, Document.created_at >= today_start)
        today_count = await self.session.scalar(stmt_today) or 0

        stmt_week = select(func.count(Document.id)).where(scope, Document.created_at >= week_start)
        week_count = await self.session.scalar(stmt_week) or 0

        extraction_rows = await self.session.scalars(
            select(Document.extraction_result).where(
                scope,
                Document.status == DocumentStatus.COMPLETED.value,
                Document.extraction_result.is_not(None),
            )
        )
        costs = [float((payload or {}).get("estimated_cost_usd", 0)) for payload in extraction_rows]

        return AnalyticsSummary(
            total_documents=total,
            completed_documents=completed,
            failed_documents=failed,
            average_confidence=round(avg_conf, 3),
            average_processing_time_ms=round(avg_time, 2),
            vlm_fallback_rate=round(vlm_rate, 3),
            documents_today=today_count,
            documents_this_week=week_count,
            average_cost_usd=round(sum(costs) / len(costs), 6) if costs else 0.0,
        )

    async def get_vendor_analytics(self, limit: int = 10) -> list[VendorAnalytics]:
        """Get spend and volume analytics by vendor."""
        # Query: group by vendor_name, count docs, sum grand_total, avg confidence
        stmt = (
            select(
                Document.vendor_name,
                Document.currency,
                func.count(Document.id).label("doc_count"),
                func.sum(Document.grand_total).label("total_spend"),
                func.avg(Document.overall_confidence).label("avg_conf"),
            )
            .where(
                Document.tenant_id == self.tenant_id,
                Document.status == DocumentStatus.COMPLETED.value,
                Document.vendor_name.is_not(None),
                Document.vendor_name != "",
            )
            .group_by(Document.vendor_name, Document.currency)
            .order_by(func.sum(Document.grand_total).desc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        vendors = []
        for row in rows:
            vendors.append(
                VendorAnalytics(
                    vendor_name=row.vendor_name,
                    document_count=row.doc_count,
                    total_spend=row.total_spend or 0.0,
                    average_confidence=round(row.avg_conf or 0.0, 3),
                    currency=row.currency or "INR",
                )
            )

        return vendors

    async def get_trends(self, days: int = 30) -> list[VolumePoint]:
        """Return portable daily volume/confidence/latency data for charts."""
        cutoff = datetime.now(UTC) - timedelta(days=days - 1)
        result = await self.session.execute(
            select(
                Document.created_at,
                Document.overall_confidence,
                Document.processing_time_ms,
            ).where(Document.tenant_id == self.tenant_id, Document.created_at >= cutoff)
        )
        buckets: dict[str, list[tuple[float, float]]] = {}
        for created_at, confidence, processing_time in result.all():
            key = created_at.date().isoformat()
            buckets.setdefault(key, []).append(
                (float(confidence or 0.0), float(processing_time or 0.0))
            )
        points = []
        for key in sorted(buckets):
            values = buckets[key]
            points.append(
                VolumePoint(
                    date=key,
                    document_count=len(values),
                    average_confidence=round(sum(v[0] for v in values) / len(values), 3),
                    average_processing_time_ms=round(sum(v[1] for v in values) / len(values), 2),
                )
            )
        return points
