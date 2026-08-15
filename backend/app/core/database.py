"""Async SQLAlchemy setup for the Supabase PostgreSQL database."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"ssl": "require"},
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""

    pass


async def init_db() -> None:
    """Verify the migrated Supabase database is reachable.

    Schema changes are intentionally owned by Alembic. The API must never
    create an untracked local schema on startup.
    """
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def get_db_session() -> AsyncSession:
    """Yield an async DB session for FastAPI dependency injection."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
