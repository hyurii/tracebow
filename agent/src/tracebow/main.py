"""
Tracebow API process.

Responsibilities:
* Initialize the Postgres engine (and warn if the wiki path is missing).
* Initialize the Git-backed wiki (idempotent ``git init``).
* Wire the ``/api/v1`` router.
* Expose ``/health`` summarizing DB / Ollama / wiki status.

Heavy work (LangGraph + LLM + integrations) runs in Celery workers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from tracebow.api.routes import router as api_router
from tracebow.config import settings
from tracebow.db import create_engine, create_sessionmaker
from tracebow.services.wiki import WikiError, WikiService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    engine = create_engine()
    app.state.db_engine = engine
    app.state.db_sessionmaker = create_sessionmaker(engine)
    logger.info("Postgres engine ready (%s)", _redact(settings.database_url))

    wiki = WikiService()
    try:
        wiki.init_if_needed()
        app.state.wiki = wiki
        logger.info("Wiki ready at %s (branch=%s)", wiki.root, wiki.default_branch)
    except WikiError as exc:
        app.state.wiki = wiki
        logger.warning("Wiki initialization failed: %s", exc)

    yield

    await engine.dispose()


app = FastAPI(
    title="Tracebow",
    description="LangGraph-based local SRE agent with a Git-backed Markdown wiki.",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health_check() -> dict[str, Any]:
    checks: dict[str, Any] = {"service": "tracebow-agent"}

    try:
        async with app.state.db_sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as exc:
        checks["database"] = f"unhealthy: {exc}"

    wiki: WikiService | None = getattr(app.state, "wiki", None)
    checks["wiki"] = "ready" if wiki and wiki.root.exists() else "missing"

    if settings.ollama_enabled:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            checks["ollama"] = "healthy"
        except Exception as exc:
            checks["ollama"] = f"unreachable: {exc}"
    else:
        checks["ollama"] = "disabled"

    checks["status"] = (
        "healthy"
        if checks.get("database") == "healthy" and checks.get("wiki") == "ready"
        else "degraded"
    )
    return checks


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Tracebow API", "docs": "/docs"}


def _redact(url: str) -> str:
    if "@" not in url:
        return url
    prefix, rest = url.rsplit("@", 1)
    scheme_sep = prefix.find("://")
    if scheme_sep < 0:
        return f"***@{rest}"
    return f"{prefix[: scheme_sep + 3]}***@{rest}"
