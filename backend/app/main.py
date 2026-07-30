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

from app.api.v1.routers import analytics, auth, documents
from app.core.config import get_settings
from app.core.database import async_session_factory, init_db
from app.core.logging import get_logger, setup_logging
from app.core.metrics import render_metrics

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

    # Initialize the database (creates tables in SQLite)
    try:
        await init_db()
        logger.info("database_initialized")
    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))
        raise

    worker_task: asyncio.Task[None] | None = None
    if settings.embedded_worker_enabled:
        # For a single free Render web service, this avoids requiring a second
        # always-running worker. Jobs remain durable in Postgres across restarts.
        from app.worker import run_worker

        worker_task = asyncio.create_task(run_worker(), name="embedded-document-worker")
        logger.info("embedded_worker_started")

    try:
        yield
    finally:
        if worker_task:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task

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
