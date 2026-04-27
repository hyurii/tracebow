"""
Shared fixtures for Tracebow's test suite.

The whole suite runs offline. Postgres is replaced by an in-memory SQLite
per test, the wiki's ``WIKI_PATH`` is a tmp dir with ``git`` initialised,
and Ollama is always disabled (``OLLAMA_ENABLED=false``).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Per-test env: SQLite in-memory, tmp wiki dir, no egress."""

    wiki_dir = tmp_path / "wiki"
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("WIKI_PATH", str(wiki_dir))
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("WIKI_SECRET_KEY", "test-fixture-key-" + "x" * 16)

    from tracebow import config as cfg

    cfg.get_settings.cache_clear()  # type: ignore[attr-defined]

    # Make sure any cached engine from a previous test is dropped
    from tracebow.db import reset_engine

    reset_engine()

    yield wiki_dir

    cfg.get_settings.cache_clear()  # type: ignore[attr-defined]
    reset_engine()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """In-memory SQLite session wired into the app's session factory."""

    from tracebow.db import Base, set_test_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = async_sessionmaker(engine, expire_on_commit=False)
    set_test_sessionmaker(sm)

    async with sm() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def wiki_service(tmp_path: Path) -> Any:
    """Git-initialised WikiService rooted at ``tmp_path/wiki``."""

    # Ensure a stable git author on the sandbox
    os.environ.setdefault("GIT_AUTHOR_NAME", "Tracebow Test")
    os.environ.setdefault("GIT_AUTHOR_EMAIL", "test@tracebow.local")
    os.environ.setdefault("GIT_COMMITTER_NAME", "Tracebow Test")
    os.environ.setdefault("GIT_COMMITTER_EMAIL", "test@tracebow.local")

    from tracebow.services.wiki import WikiService

    svc = WikiService(root=tmp_path / "wiki")
    svc.init_if_needed()
    return svc
