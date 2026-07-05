"""
Celery task definitions for Tracebow.

Three responsibilities:
* ``run_*_rca`` / ``run_chat`` — execute the LangGraph orchestrator and
  persist the verdict into Postgres so the portal can show it.
* ``health_check_ollama`` / ``cleanup_stale_results`` — maintenance.
* ``backup_wiki`` — optional hourly push of the Git wiki to a remote
  (only if an operator configured one via the portal).

All tasks run sync; the graph is awaited inside a fresh event loop.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select

from tracebow.celery_app import app
from tracebow.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _maybe_fetch_diff(
    provider: str, identifier: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    """Fetch the latest failing diff; never raise into the RCA path."""
    try:
        from tracebow.services.repohost import fetch_latest_diff

        return fetch_latest_diff(provider, identifier, payload)
    except Exception:
        logger.exception("Diff fetch failed for %s:%s", provider, identifier)
        return None


async def _persist_failure_and_rca(
    task_id: str,
    event_type: str,
    payload: dict[str, Any],
    rca_result: dict[str, Any],
    diff: dict[str, Any] | None = None,
) -> None:
    """Write one Failure + one RcaReport (plus an optional Stacktrace/diff)."""
    from tracebow.db import CommitDiff, Failure, RcaReport, Stacktrace, get_session_factory

    stacktrace_text = (
        payload.get("log_content")
        or payload.get("console_output")
        or payload.get("log")
        or payload.get("stacktrace")
        or ""
    )

    sm = get_session_factory()
    async with sm() as session:
        failure = Failure(
            source=event_type,
            status="analyzed",
            repo=payload.get("repository") or payload.get("repo"),
            job_name=payload.get("job_name") or payload.get("workflow_name"),
            build_number=_as_int(payload.get("build_number")),
            run_id=_as_int(payload.get("run_id")),
            pr_number=_as_str(payload.get("pr_number") or payload.get("pull_request_number")),
            commit_sha=payload.get("commit_sha")
            or payload.get("git_commit")
            or payload.get("head_sha"),
            branch=payload.get("branch") or payload.get("git_branch") or payload.get("head_branch"),
            build_url=payload.get("build_url") or payload.get("run_url"),
            task_id=task_id,
        )
        session.add(failure)
        await session.flush()

        if stacktrace_text:
            all_lines = stacktrace_text.splitlines()
            snippet = "\n".join(all_lines[-50:])
            session.add(
                Stacktrace(
                    failure_id=failure.id,
                    excerpt=snippet,
                    line_count=len(all_lines),
                    full_text=stacktrace_text,
                )
            )

        session.add(
            RcaReport(
                failure_id=failure.id,
                summary=rca_result.get("summary", ""),
                branch_taken=rca_result.get("branch_taken", "novel_reasoned"),
                wiki_doc_path=rca_result.get("wiki_doc_path"),
                wiki_doc_created=bool(rca_result.get("wiki_doc_created")),
                tool_trace=rca_result.get("tool_trace"),
                model_used=rca_result.get("model_used"),
                latency_ms=rca_result.get("latency_ms"),
            )
        )

        if diff and diff.get("patch"):
            session.add(
                CommitDiff(
                    failure_id=failure.id,
                    provider=diff.get("provider", event_type),
                    ref=diff.get("ref"),
                    files_changed=int(diff.get("files_changed") or 0),
                    additions=int(diff.get("additions") or 0),
                    deletions=int(diff.get("deletions") or 0),
                    patch=diff.get("patch"),
                    truncated=bool(diff.get("truncated")),
                )
            )

        await session.commit()


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _execute_rca(task_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    from tracebow.agent import RCAAgent
    from tracebow.services import repo_access

    # Register the source (ingress is always accepted) so it shows up in the
    # portal's Repositories view and can be granted outbound access.
    source = repo_access.derive_source(event_type, payload)
    if source is not None:
        repo_access.register_repository_sync(*source)

    agent = RCAAgent()
    result: dict[str, Any] = _run_async(agent.analyze(event_type, payload))
    result["task_id"] = task_id

    # Gate outbound access and (when allowed) capture the latest failing diff.
    diff: dict[str, Any] | None = None
    if source is not None:
        provider, identifier = source
        access = repo_access.check_access_sync(
            provider,
            identifier,
            reason=f"RCA for {event_type} event on {identifier}",
        )
        result["repo_access"] = access
        if access == repo_access.ALLOWED:
            diff = _maybe_fetch_diff(provider, identifier, payload)

    try:
        _run_async(_persist_failure_and_rca(task_id, event_type, payload, result, diff))
    except Exception:
        # Persistence must never break the RCA response.
        logger.exception("Failed to persist Failure / RcaReport (task=%s)", task_id)

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
def run_rca(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
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
    payload = {
        "repository": repository,
        "job_name": job_name,
        "log_content": log_content,
        "pr_number": pr_number,
        "build_url": build_url,
        "query": f"Analyze build failure for {repository} job {job_name}",
    }
    try:
        return _execute_rca(self.request.id, "cli", payload)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@app.task(
    bind=True,
    name="tracebow.tasks.run_chat",
    max_retries=2,
    default_retry_delay=10,
    rate_limit=get_settings().celery_rca_rate_limit,
    acks_late=True,
)
def run_chat(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    from tracebow.agent import run_rca_agent

    try:
        response = _run_async(run_rca_agent(query=message, context=context or {}))
        return {"response": response, "context_used": bool(context)}
    except Exception as exc:
        logger.exception("Chat task failed")
        raise self.retry(exc=exc) from exc


# ---------------------------------------------------------------------------
# Periodic maintenance
# ---------------------------------------------------------------------------


@app.task(name="tracebow.tasks.health_check_ollama")
def health_check_ollama() -> dict[str, Any]:
    s = get_settings()
    if not s.ollama_enabled:
        return {"status": "disabled"}

    url = f"{s.ollama_base_url}/api/tags"
    start = time.monotonic()
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        elapsed = round((time.monotonic() - start) * 1000)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"status": "healthy", "latency_ms": elapsed, "models": models}
    except Exception as exc:
        elapsed = round((time.monotonic() - start) * 1000)
        logger.error("Ollama health check failed (%dms): %s", elapsed, exc)
        return {"status": "unhealthy", "latency_ms": elapsed, "error": str(exc)}


@app.task(name="tracebow.tasks.cleanup_stale_results")
def cleanup_stale_results() -> dict[str, Any]:
    s = get_settings()
    try:
        import redis as redis_lib

        r = redis_lib.from_url(s.redis_url)
        cleaned = 0
        for key in r.scan_iter(match="celery-task-meta-*", count=500):
            if r.ttl(key) == -1:
                r.expire(key, s.celery_task_result_ttl)
                cleaned += 1
        return {"cleaned": cleaned}
    except Exception as exc:
        logger.warning("Result cleanup failed: %s", exc)
        return {"error": str(exc)}


@app.task(name="tracebow.tasks.backup_wiki")
def backup_wiki(manual: bool = False) -> dict[str, Any]:
    """Push the wiki to the configured remote.

    Runs hourly via beat but self-rate-limits using ``auto_backup_hours``:
    if the last successful push was less than that many hours ago, it
    exits early. Manual invocations (``manual=True``) ignore the rate
    limit.
    """
    from tracebow.db import WikiBackupLog, WikiSettings, get_session_factory
    from tracebow.services.secrets import decrypt
    from tracebow.services.wiki import WikiError, WikiService

    async def _run() -> dict[str, Any]:
        sm = get_session_factory()
        async with sm() as session:
            row = (await session.execute(select(WikiSettings).limit(1))).scalars().first()
            if row is None or not row.remote_url:
                return {"status": "skipped", "reason": "no remote configured"}
            if not manual and not row.enabled:
                return {"status": "skipped", "reason": "backup disabled"}

            if (
                not manual
                and row.auto_backup_hours
                and row.last_backup_at
                and row.last_backup_status == "ok"
            ):
                delta = dt.datetime.utcnow() - row.last_backup_at
                if delta < dt.timedelta(hours=row.auto_backup_hours):
                    return {"status": "skipped", "reason": "not due"}

            deploy_key: str | None = None
            if row.deploy_key_encrypted:
                try:
                    deploy_key = decrypt(row.deploy_key_encrypted)
                except ValueError as exc:
                    await _record_backup(
                        session, row, "error", f"deploy key decrypt failed: {exc}", manual
                    )
                    return {"status": "error", "error": "deploy key decrypt failed"}

            try:
                message = WikiService().push(
                    remote_url=row.remote_url,
                    branch=row.remote_branch or "main",
                    deploy_key_pem=deploy_key,
                )
                await _record_backup(session, row, "ok", message, manual)
                return {"status": "ok", "message": message}
            except WikiError as exc:
                await _record_backup(session, row, "error", str(exc), manual)
                return {"status": "error", "error": str(exc)}

    async def _record_backup(
        session: Any,
        row: Any,
        status: str,
        message: str,
        manual_flag: bool,
    ) -> None:
        session.add(
            WikiBackupLog(
                status=status,
                message=message,
                triggered_by="manual" if manual_flag else "auto",
            )
        )
        row.last_backup_status = status
        row.last_backup_message = message
        row.last_backup_at = dt.datetime.utcnow()
        await session.commit()

    outcome: dict[str, Any] = _run_async(_run())
    return outcome
