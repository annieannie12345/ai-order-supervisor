"""
db/session.py

Async SQLAlchemy engine + session factory for PostgreSQL (asyncpg driver),
and the FastAPI `get_session` dependency used across `api/routers/*`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Final

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
#
# `settings.database_url` is expected to use the asyncpg driver, e.g.:
#   postgresql+asyncpg://user:password@host:5432/dbname
#
# `pool_pre_ping` guards against stale connections after DB restarts/idle
# timeouts. Size DB_POOL_SIZE + DB_MAX_OVERFLOW against
# WORKER_MAX_CONCURRENT_ACTIVITIES, especially when many activities can
# persist snapshots concurrently.
#
# NOTE: `future=True` was removed — it was a SQLAlchemy 1.4 migration-bridge
# flag with no effect (and no meaning) in SQLAlchemy 2.0, where "future"
# behavior is simply the only behavior.

engine: Final[AsyncEngine] = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

# --------------------------------------------------------------------------
# Session factory
# --------------------------------------------------------------------------
#
# expire_on_commit=False keeps ORM instances usable (e.g. for response
# serialization) after the session commits, without triggering a refresh
# query for every attribute access.
#
# NOTE: `autocommit` was removed — it was a legacy Session 1.x flag and is
# no longer a valid kwarg for AsyncSession/sessionmaker in SQLAlchemy 2.0.
# Passing it raised TypeError at import time.

async_session_factory: Final[async_sessionmaker[AsyncSession]] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# --------------------------------------------------------------------------
# FastAPI dependency
# --------------------------------------------------------------------------


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding a request-scoped `AsyncSession`.

    Commits on clean exit, rolls back on exception, and always closes the
    session/returns the connection to the pool. Callers (routers/activities)
    are responsible for calling `session.commit()` explicitly after writes
    if they want changes visible before the request completes; this
    dependency's commit is a safety net for the common case.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """
    Dispose of the engine's connection pool. Call this from FastAPI's
    shutdown handler (`main.py`) to close all pooled connections cleanly.
    """
    await engine.dispose()
