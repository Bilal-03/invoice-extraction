"""
FastAPI application entry point.
"""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text

from app.api.v1.routers import analytics, ap, auth, documents
from app.core.config import get_settings
from app.core.database import async_session_factory, init_db
from app.core.logging import get_logger, setup_logging
from app.core.metrics import render_metrics
from app.core.tracing import configure_tracing, shutdown_tracing

# Initialize structlog before creating the app
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events.
    Setup happens before the yield, teardown happens after.
    """
    # Startup
    logger.info("application_startup")

    # Verify the Alembic-managed Supabase schema is reachable.
    try:
        await init_db()
        logger.info("database_initialized")
    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))
        raise

    worker_task: asyncio.Task[None] | None = None
    if settings.embedded_worker_enabled:
        # Budget mode for a single Render Web Service. Jobs remain durable in
        # Postgres, but OCR shares this process and stops when Render sleeps it.
        from app.worker import run_worker

        worker_task = asyncio.create_task(run_worker(), name="embedded-document-worker")
        logger.warning("embedded_worker_started", mode="single_service_budget_mode")

    try:
        yield
    finally:
        if worker_task:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
        shutdown_tracing()

    # Shutdown
    logger.info("application_shutdown")


# Create FastAPI application
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Intelligent Document Processing platform for invoice extraction.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)
configure_tracing(app)

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(documents.router, prefix=f"/api/{settings.api_version}")
app.include_router(ap.router, prefix=f"/api/{settings.api_version}")
app.include_router(analytics.router, prefix=f"/api/{settings.api_version}")
app.include_router(auth.router, prefix=f"/api/{settings.api_version}")


@app.get("/health", tags=["system"])
async def health_check():
    """Liveness probe."""
    return {"status": "healthy", "environment": settings.environment.value}


@app.get("/ready", tags=["system"])
async def readiness_check():
    """Readiness probe that verifies the metadata database is reachable."""
    async with async_session_factory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


# Global exception handler to ensure JSON responses and logging
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
