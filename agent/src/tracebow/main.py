"""
Tracebow - Local Agent-Driven RAG Platform for CI/CD Root Cause Analysis.

Main FastAPI application providing:
- Webhook endpoints for Jenkins/GitHub integration
- MCP tool registry for agentic reasoning
- REST API for the Developer Portal

Heavy work (LLM inference, retrieval) is dispatched to Celery workers
via RabbitMQ.  Results are stored in Redis and polled via GET /api/v1/tasks/{id}.
"""

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router as api_router
from .config import settings
from .mcp.tools import MCPToolRegistry
from .services.graph import GraphService
from .services.retrieval import RetrievalService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, cleanup on shutdown."""
    app.state.mcp_registry = MCPToolRegistry()
    app.state.retrieval = RetrievalService()
    app.state.graph = GraphService()

    app.state.redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    logger.info("Redis connection pool ready (%s)", settings.redis_url)

    yield

    await app.state.redis.close()
    if hasattr(app.state.retrieval, "close"):
        await app.state.retrieval.close()


app = FastAPI(
    title="Tracebow",
    description="Local Agent-Driven RAG Platform for CI/CD Root Cause Analysis",
    version="0.1.0",
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
async def health_check():
    """Health check for container orchestration."""
    checks: dict = {"service": "tracebow-agent"}

    try:
        await app.state.redis.ping()
        checks["redis"] = "healthy"
    except Exception:
        checks["redis"] = "unhealthy"

    overall = "healthy" if checks.get("redis") == "healthy" else "degraded"
    checks["status"] = overall
    return checks


@app.get("/")
async def root():
    """Root redirect to API docs."""
    return {"message": "Tracebow API", "docs": "/docs"}
