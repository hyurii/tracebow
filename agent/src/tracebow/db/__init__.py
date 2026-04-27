"""Tracebow telemetry database package.

Postgres in production, SQLite (aiosqlite) in tests/CLI. Switch via
``DATABASE_URL``. All tables are declared in :mod:`tracebow.db.models`.
"""

from tracebow.db.models import (
    Base,
    Failure,
    RcaReport,
    Stacktrace,
    WikiBackupLog,
    WikiSettings,
)
from tracebow.db.session import (
    create_engine,
    create_sessionmaker,
    get_async_session,
    get_session_factory,
    reset_engine,
    session_scope,
    set_test_sessionmaker,
)

__all__ = [
    "Base",
    "Failure",
    "RcaReport",
    "Stacktrace",
    "WikiBackupLog",
    "WikiSettings",
    "create_engine",
    "create_sessionmaker",
    "get_async_session",
    "get_session_factory",
    "reset_engine",
    "session_scope",
    "set_test_sessionmaker",
]
