"""
Analytics endpoints.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import get_tenant_id, verify_auth
from app.domain.schemas import AnalyticsSummary, AnalyticsTrendsResponse, AnalyticsVendorsResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(verify_auth)])


@router.get("/summary", response_model=AnalyticsSummary)
async def get_summary(
    db: AsyncSession = Depends(get_db_session), tenant_id: str = Depends(get_tenant_id)
):
    """Get overall platform metrics (volume, avg confidence, processing time)."""
    service = AnalyticsService(db, tenant_id)
    return await service.get_summary()


@router.get("/vendors", response_model=AnalyticsVendorsResponse)
async def get_vendor_analytics(
    limit: int = 10,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Get spend and volume analytics broken down by vendor."""
    service = AnalyticsService(db, tenant_id)
    vendors = await service.get_vendor_analytics(limit=limit)
    return AnalyticsVendorsResponse(vendors=vendors)


@router.get("/trends", response_model=AnalyticsTrendsResponse)
async def get_trends(
    days: int = 30,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_tenant_id),
):
    service = AnalyticsService(db, tenant_id)
    return AnalyticsTrendsResponse(points=await service.get_trends(days=max(1, min(days, 365))))
