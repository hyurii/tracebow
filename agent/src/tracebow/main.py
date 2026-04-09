"""
Tracebow - Local Agent-Driven RAG Platform for CI/CD Root Cause Analysis.

Main FastAPI application providing:
- Webhook endpoints for Jenkins/GitHub integration
- MCP tool registry for agentic reasoning
- REST API for the Developer Portal
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .api.routes import router as api_router
from .mcp.tools import MCPToolRegistry
from .services.retrieval import RetrievalService
from .services.graph import GraphService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, cleanup on shutdown."""
    app.state.mcp_registry = MCPToolRegistry()
    app.state.retrieval = RetrievalService()
    app.state.graph = GraphService()
    yield
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
    return {"status": "healthy", "service": "tracebow-agent"}


@app.get("/")
async def root():
    """Root redirect to API docs."""
    return {"message": "Tracebow API", "docs": "/docs"}
