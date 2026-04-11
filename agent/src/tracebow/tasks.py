"""
Celery task definitions for Tracebow.

All heavy work (LLM inference, retrieval, graph queries) runs here
instead of inside the FastAPI process.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from tracebow.celery_app import app
from tracebow.config import get_settings

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine inside a sync Celery worker."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _execute_rca(task_id: str, event_type: str, payload: dict) -> dict:
    """Shared RCA execution logic used by all RCA task variants."""
    from tracebow.agent import RCAAgent

    agent = RCAAgent()
    result = _run_async(agent.analyze(event_type, payload))
    result["task_id"] = task_id
    return result


# ---------------------------------------------------------------------------
# RCA tasks
# ---------------------------------------------------------------------------


@app.task(
    bind=True,
    name="tracebow.tasks.run_rca",
    max_retries=3,
    default_retry_delay=30,
    rate_limit=get_settings().celery_rca_rate_limit,
    acks_late=True,
)
def run_rca(
    self,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Core RCA task — runs the full agentic analysis pipeline.
    Retries on transient failures (Ollama down, ChromaDB timeout).
    """
    try:
        return _execute_rca(self.request.id, event_type, payload)
    except Exception as exc:
        logger.exception(
            "RCA task failed (attempt %d/%d)",
            self.request.retries + 1,
            self.max_retries + 1,
        )
        raise self.retry(exc=exc) from exc


@app.task(
    bind=True,
    name="tracebow.tasks.run_jenkins_rca",
    max_retries=3,
    default_retry_delay=30,
    rate_limit=get_settings().celery_rca_rate_limit,
    acks_late=True,
)
def run_jenkins_rca(
    self,
    job_name: str,
    build_number: int,
    git_commit: str | None = None,
    git_branch: str | None = None,
    console_url: str | None = None,
    build_url: str | None = None,
) -> dict[str, Any]:
    """RCA for Jenkins pipeline failures."""
    payload = {
        "job_name": job_name,
        "build_number": build_number,
        "git_commit": git_commit,
        "git_branch": git_branch,
        "console_url": console_url,
        "build_url": build_url,
    }
    try:
        return _execute_rca(self.request.id, "jenkins", payload)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@app.task(
    bind=True,
    name="tracebow.tasks.run_github_rca",
    max_retries=3,
    default_retry_delay=30,
    rate_limit=get_settings().celery_rca_rate_limit,
    acks_late=True,
)
def run_github_rca(
    self,
    repository: str,
    run_id: int,
    head_sha: str | None = None,
    head_branch: str | None = None,
    pr_number: int | None = None,
    workflow_name: str | None = None,
    run_url: str | None = None,
) -> dict[str, Any]:
    """RCA for GitHub Actions workflow failures."""
    payload = {
        "repository": repository,
        "run_id": run_id,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "pull_request_number": pr_number,
        "workflow_name": workflow_name,
        "run_url": run_url,
    }
    try:
        return _execute_rca(self.request.id, "github", payload)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@app.task(
    bind=True,
    name="tracebow.tasks.run_cli_rca",
    max_retries=3,
    default_retry_delay=30,
    rate_limit=get_settings().celery_rca_rate_limit,
    acks_late=True,
)
def run_cli_rca(
    self,
    repository: str,
    job_name: str,
    log_content: str,
    pr_number: str | None = None,
    build_url: str | None = None,
) -> dict[str, Any]:
    """RCA for logs submitted by the Go CLI agent."""
    payload = {
        "repository": repository,
        "job_name": job_name,
        "log_content": log_content,
        "pr_number": pr_number,
        "build_url": build_url,
        "query": (f"Analyze build failure for {repository} job {job_name}"),
    }
    try:
        return _execute_rca(self.request.id, "cli", payload)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


# ---------------------------------------------------------------------------
# Chat task (async via queue so the API stays responsive)
# ---------------------------------------------------------------------------


@app.task(
    bind=True,
    name="tracebow.tasks.run_chat",
    max_retries=2,
    default_retry_delay=10,
    rate_limit=get_settings().celery_rca_rate_limit,
    acks_late=True,
)
def run_chat(
    self,
    message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chat with the RCA agent."""
    from tracebow.agent import run_rca_agent

    try:
        response = _run_async(
            run_rca_agent(query=message, context=context or {}),
        )
        return {
            "response": response,
            "context_used": bool(context),
        }
    except Exception as exc:
        logger.exception("Chat task failed")
        raise self.retry(exc=exc) from exc


# ---------------------------------------------------------------------------
# Periodic maintenance tasks
# ---------------------------------------------------------------------------


@app.task(name="tracebow.tasks.health_check_ollama")
def health_check_ollama() -> dict[str, Any]:
    """Ping Ollama to verify it is responsive."""
    s = get_settings()
    url = f"{s.ollama_base_url}/api/tags"
    start = time.monotonic()
    try:
        resp = httpx.get(url, timeout=10)
        elapsed = round((time.monotonic() - start) * 1000)
        models = [m["name"] for m in resp.json().get("models", [])]
        logger.info(
            "Ollama healthy (%dms), models: %s",
            elapsed,
            models,
        )
        return {
            "status": "healthy",
            "latency_ms": elapsed,
            "models": models,
        }
    except Exception as exc:
        elapsed = round((time.monotonic() - start) * 1000)
        logger.error(
            "Ollama health check failed (%dms): %s",
            elapsed,
            exc,
        )
        return {
            "status": "unhealthy",
            "latency_ms": elapsed,
            "error": str(exc),
        }


@app.task(name="tracebow.tasks.cleanup_stale_results")
def cleanup_stale_results() -> dict[str, Any]:
    """
    Ensure TTL on task result keys in Redis.

    Redis EXPIRE handles most of this automatically, but this task
    catches keys that were stored without expiry.
    """
    s = get_settings()
    try:
        import redis as redis_lib

        r = redis_lib.from_url(s.redis_url)
        cleaned = 0
        cursor = r.scan_iter(
            match="celery-task-meta-*",
            count=500,
        )
        for key in cursor:
            if r.ttl(key) == -1:
                r.expire(key, s.celery_task_result_ttl)
                cleaned += 1
        logger.info(
            "Result cleanup: ensured TTL on %d keys",
            cleaned,
        )
        return {"cleaned": cleaned}
    except Exception as exc:
        logger.warning("Result cleanup failed: %s", exc)
        return {"error": str(exc)}


@app.task(name="tracebow.tasks.cleanup_embedding_cache")
def cleanup_embedding_cache() -> dict[str, Any]:
    """
    Placeholder for embedding cache maintenance.
    Extend with ChromaDB compaction or stale vector pruning.
    """
    logger.info("Embedding cache cleanup — no-op for now")
    return {"status": "ok", "message": "placeholder"}
