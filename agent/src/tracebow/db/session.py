"""Async SQLAlchemy engine + session management.

Two consumers:
- FastAPI: Depends(get_async_session) — one session per request.
- Celery tasks: session_scope() — sync wrapper around a short-lived async session.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tracebow.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_engine(url: str | None = None) -> AsyncEngine:
    """Create (or return cached) async engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        dsn = url or settings.database_url
        kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if dsn.startswith("sqlite"):
            # aiosqlite doesn't benefit from pool sizing.
            kwargs.pop("pool_pre_ping", None)
        _engine = create_async_engine(dsn, **kwargs)
    return _engine


def create_sessionmaker(engine: AsyncEngine | None = None) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        eng = engine or create_engine()
        _sessionmaker = async_sessionmaker(eng, expire_on_commit=False)
    return _sessionmaker


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker()


def set_test_sessionmaker(sessionmaker_: async_sessionmaker[AsyncSession]) -> None:
    """Test hook: replace the module-level sessionmaker.

    Lets tests spin up a fresh in-memory SQLite per test and then call this
    so any code path using ``get_session_factory()`` uses that database.
    """
    global _sessionmaker
    _sessionmaker = sessionmaker_


def reset_engine() -> None:
    """Drop the cached engine + sessionmaker (tests only)."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Yields one session per request."""
    sm = get_session_factory()
    async with sm() as session:
        yield session


@asynccontextmanager
async def _session_ctx() -> AsyncIterator[AsyncSession]:
    sm = get_session_factory()
    async with sm() as session:
        yield session


def session_scope() -> Any:
    """Sync-friendly context manager used from Celery tasks.

    Usage::

        with session_scope() as sync_runner:
            sync_runner(some_async_fn(...))
    """

    loop = asyncio.new_event_loop()

    class _Runner:
        def __enter__(self_inner) -> Any:  # noqa: N805
            return self_inner.run

        def __exit__(self_inner, *_: object) -> None:  # noqa: N805
            loop.close()

        @staticmethod
        def run(coro: Any) -> Any:
            return loop.run_until_complete(coro)

    return _Runner()
