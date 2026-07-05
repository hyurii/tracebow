"""Tracebow API routes.

Three groups:

* **CI ingress** — ``/analyze``, ``/webhooks/{jenkins,github}`` — enqueue a
  Celery task; return 202 + task id.
* **Telemetry read** — ``/failures``, ``/failures/{id}``, ``/failures/{id}/rca``,
  ``/tasks/{task_id}`` — what the portal polls.
* **Wiki + settings** — ``/wiki/*`` (read-only for now), ``/settings/backup``,
  ``/settings/backup/trigger``.

The layer deliberately does no LLM work; all of that is pushed to Celery.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracebow.celery_app import app as celery_app
from tracebow.config import settings
from tracebow.db import (
    AccessRequest,
    EgressEvent,
    Failure,
    RcaReport,
    Repository,
    Stacktrace,
    WikiSettings,
    get_async_session,
)
from tracebow.services import repo_access
from tracebow.services.egress import EXTERNAL, INTERNAL, classify_host
from tracebow.services.secrets import decrypt, encrypt, fingerprint
from tracebow.services.wiki import WikiError, WikiService
from tracebow.tasks import (
    backup_wiki,
    run_chat,
    run_cli_rca,
    run_github_rca,
    run_jenkins_rca,
    run_rca,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["api"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class JenkinsWebhookPayload(BaseModel):
    job_name: str = Field(..., description="Jenkins job name")
    build_number: int
    git_commit: str | None = None
    git_branch: str | None = None
    console_url: str | None = None
    build_url: str | None = None


class GitHubWebhookPayload(BaseModel):
    repository: str
    run_id: int
    run_url: str | None = None
    head_sha: str | None = None
    head_branch: str | None = None
    pull_request_number: int | None = None
    workflow_name: str | None = None
    event: str | None = None


class CLIAnalyzePayload(BaseModel):
    repository: str
    pr_number: str | None = None
    job_name: str = "unknown-job"
    build_url: str | None = None
    log_content: str


class RCARequest(BaseModel):
    source: str
    job_name_or_repo: str
    build_number_or_run_id: int | str
    additional_context: str | None = None


class ChatRequest(BaseModel):
    message: str
    context: dict[str, Any] | None = None


class TaskAccepted(BaseModel):
    status: str = "accepted"
    task_id: str
    poll_url: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


class FailureSummary(BaseModel):
    id: str
    source: str
    status: str
    repo: str | None
    job_name: str | None
    build_number: int | None
    run_id: int | None
    pr_number: str | None
    commit_sha: str | None
    branch: str | None
    build_url: str | None
    task_id: str | None
    triggered_at: str | None
    rca_summary: str | None


class FailureDetail(FailureSummary):
    stacktraces: list[dict[str, Any]]
    diffs: list[dict[str, Any]] = []
    rca: dict[str, Any] | None


class WikiDocSummary(BaseModel):
    path: str
    title: str
    size_bytes: int
    updated_at: str | None


class WikiListResponse(BaseModel):
    docs: list[WikiDocSummary]


class WikiHit(BaseModel):
    path: str
    title: str
    snippet: str
    score: float


class WikiSearchResponse(BaseModel):
    query: str
    hits: list[WikiHit]


class WikiDocResponse(BaseModel):
    path: str
    title: str
    content: str
    updated_at: str | None
    size_bytes: int


class BackupConfigUpdate(BaseModel):
    """Payload sent by the portal's Settings > Backup form."""

    enabled: bool = False
    remote_url: str | None = None
    branch: str = "main"
    auto_backup_hours: int | None = None
    # Only present when rotating. ``None`` = clear, omitted = keep existing.
    deploy_key: str | None = None


class BackupConfigResponse(BaseModel):
    enabled: bool
    remote_url: str | None
    branch: str
    auto_backup_hours: int | None
    has_deploy_key: bool
    deploy_key_fingerprint: str | None
    last_backup_at: str | None
    last_backup_status: str | None
    last_backup_error: str | None


class RepositoryUpdate(BaseModel):
    """Payload for the portal's Repositories page."""

    access_status: str | None = None  # allowed | denied | pending
    auth_method: str | None = None
    display_name: str | None = None
    # Present only when setting/rotating; None clears, omitted keeps existing.
    credential: str | None = None


class AccessRequestResolve(BaseModel):
    decision: str  # approved | denied


# ---------------------------------------------------------------------------
# CI ingress
# ---------------------------------------------------------------------------


@router.post("/analyze", response_model=TaskAccepted, status_code=202)
async def analyze_from_cli(payload: CLIAnalyzePayload) -> TaskAccepted:
    task = run_cli_rca.apply_async(
        kwargs={
            "repository": payload.repository,
            "job_name": payload.job_name,
            "log_content": payload.log_content,
            "pr_number": payload.pr_number,
            "build_url": payload.build_url,
        },
        queue="rca",
    )
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


@router.post("/webhooks/jenkins", response_model=TaskAccepted, status_code=202)
async def jenkins_webhook(payload: JenkinsWebhookPayload) -> TaskAccepted:
    if not settings.jenkins_url:
        raise HTTPException(503, "Jenkins integration not configured (JENKINS_URL)")

    task = run_jenkins_rca.apply_async(
        kwargs={
            "job_name": payload.job_name,
            "build_number": payload.build_number,
            "git_commit": payload.git_commit,
            "git_branch": payload.git_branch,
            "console_url": payload.console_url,
            "build_url": payload.build_url,
        },
        queue="rca",
    )
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


@router.post("/webhooks/github", response_model=TaskAccepted, status_code=202)
async def github_webhook(payload: GitHubWebhookPayload) -> TaskAccepted:
    if not settings.github_token:
        raise HTTPException(503, "GitHub integration not configured (GITHUB_TOKEN)")

    task = run_github_rca.apply_async(
        kwargs={
            "repository": payload.repository,
            "run_id": payload.run_id,
            "head_sha": payload.head_sha,
            "head_branch": payload.head_branch,
            "pr_number": payload.pull_request_number,
            "workflow_name": payload.workflow_name,
            "run_url": payload.run_url,
        },
        queue="rca",
    )
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


@router.post("/rca", response_model=TaskAccepted, status_code=202)
async def trigger_rca(request: RCARequest) -> TaskAccepted:
    payload: dict[str, Any] = {}
    if request.source == "jenkins":
        payload = {
            "job_name": request.job_name_or_repo,
            "build_number": request.build_number_or_run_id,
        }
    elif request.source == "github":
        payload = {
            "repository": request.job_name_or_repo,
            "run_id": request.build_number_or_run_id,
        }
    if request.additional_context:
        payload["additional_context"] = request.additional_context

    task = run_rca.apply_async(args=[request.source, payload], queue="rca")
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


@router.post("/chat", response_model=TaskAccepted, status_code=202)
async def chat_with_agent(request: ChatRequest) -> TaskAccepted:
    task = run_chat.apply_async(
        kwargs={"message": request.message, "context": request.context},
        queue="rca",
    )
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


# ---------------------------------------------------------------------------
# Telemetry reads
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)
    response = TaskStatusResponse(task_id=task_id, status=result.status)
    if result.ready():
        if result.successful():
            response.result = result.result
        else:
            response.error = str(result.result)
    return response


@router.get("/failures")
async def list_failures(
    session: AsyncSession = Depends(get_async_session),
    limit: int = 100,
) -> dict[str, Any]:
    stmt = (
        select(Failure)
        .options(selectinload(Failure.rca_reports))
        .order_by(Failure.triggered_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    rows = (await session.execute(stmt)).scalars().all()
    total = (await session.execute(select(func.count()).select_from(Failure))).scalar_one()
    return {
        "failures": [f.to_dict() for f in rows],
        "total": int(total),
    }


@router.get("/failures/{failure_id}", response_model=FailureDetail)
async def get_failure(
    failure_id: str,
    session: AsyncSession = Depends(get_async_session),
    include_full: bool = False,
) -> FailureDetail:
    stmt = (
        select(Failure)
        .options(
            selectinload(Failure.stacktraces),
            selectinload(Failure.rca_reports),
            selectinload(Failure.commit_diffs),
        )
        .where(Failure.id == failure_id)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise HTTPException(404, "Failure not found")

    latest_rca = row.rca_reports[-1] if row.rca_reports else None
    rca_dict: dict[str, Any] | None = None
    if latest_rca is not None:
        rca_dict = {
            "id": latest_rca.id,
            "summary": latest_rca.summary,
            "branch_taken": latest_rca.branch_taken,
            "wiki_doc_path": latest_rca.wiki_doc_path,
            "wiki_doc_created": latest_rca.wiki_doc_created,
            "model_used": latest_rca.model_used,
            "tool_trace": latest_rca.tool_trace,
            "latency_ms": latest_rca.latency_ms,
            "created_at": (
                latest_rca.created_at.isoformat() if latest_rca.created_at is not None else None
            ),
        }

    return FailureDetail(
        **row.to_dict(),
        stacktraces=[
            {
                "id": s.id,
                "excerpt": s.excerpt,
                "line_count": s.line_count,
                "language": s.language,
                "full_text": s.full_text if include_full else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in row.stacktraces
        ],
        diffs=[
            {
                "id": d.id,
                "provider": d.provider,
                "ref": d.ref,
                "files_changed": d.files_changed,
                "additions": d.additions,
                "deletions": d.deletions,
                "patch": d.patch,
                "truncated": d.truncated,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in row.commit_diffs
        ],
        rca=rca_dict,
    )


@router.get("/failures/{failure_id}/rca")
async def get_failure_rca(
    failure_id: str,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    stmt = (
        select(RcaReport)
        .where(RcaReport.failure_id == failure_id)
        .order_by(RcaReport.created_at.desc())
        .limit(1)
    )
    rca = (await session.execute(stmt)).scalars().first()
    if rca is None:
        raise HTTPException(404, "No RCA for this failure yet")
    return {
        "summary": rca.summary,
        "branch_taken": rca.branch_taken,
        "wiki_doc_path": rca.wiki_doc_path,
        "wiki_doc_created": rca.wiki_doc_created,
        "model_used": rca.model_used,
        "tool_trace": rca.tool_trace,
    }


# ---------------------------------------------------------------------------
# Wiki (read-only from the API layer; writes happen via the agent)
# ---------------------------------------------------------------------------


@router.get("/wiki", response_model=WikiListResponse)
async def list_wiki_docs(request: Request) -> WikiListResponse:
    svc: WikiService = request.app.state.wiki
    try:
        docs = svc.list_docs()
    except WikiError as exc:
        raise HTTPException(500, str(exc)) from exc
    return WikiListResponse(
        docs=[
            WikiDocSummary(
                path=d.path,
                title=d.title,
                size_bytes=d.size,
                updated_at=d.updated_at,
            )
            for d in docs
        ],
    )


@router.get("/wiki/search", response_model=WikiSearchResponse)
async def search_wiki_docs(request: Request, q: str, limit: int = 10) -> WikiSearchResponse:
    svc: WikiService = request.app.state.wiki
    hits = svc.search(q, limit=max(1, min(limit, 50)))
    return WikiSearchResponse(
        query=q,
        hits=[WikiHit(path=h.path, title=h.title, snippet=h.excerpt, score=h.score) for h in hits],
    )


@router.get("/wiki/doc", response_model=WikiDocResponse)
async def read_wiki_doc(request: Request, path: str) -> WikiDocResponse:
    svc: WikiService = request.app.state.wiki
    try:
        doc = svc.read(path)
    except WikiError as exc:
        raise HTTPException(404, str(exc)) from exc
    return WikiDocResponse(
        path=doc.path,
        title=doc.title,
        content=doc.content,
        size_bytes=doc.size,
        updated_at=doc.updated_at,
    )


# ---------------------------------------------------------------------------
# Backup settings + trigger
# ---------------------------------------------------------------------------


async def _get_or_create_settings(session: AsyncSession) -> WikiSettings:
    row = (await session.execute(select(WikiSettings).limit(1))).scalars().first()
    if row is None:
        row = WikiSettings(id=1, remote_branch="main", enabled=False)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def _settings_to_response(row: WikiSettings) -> BackupConfigResponse:
    return BackupConfigResponse(
        enabled=row.enabled,
        remote_url=row.remote_url,
        branch=row.remote_branch,
        auto_backup_hours=row.auto_backup_hours,
        has_deploy_key=row.deploy_key_encrypted is not None,
        deploy_key_fingerprint=row.deploy_key_fingerprint,
        last_backup_at=row.last_backup_at.isoformat() if row.last_backup_at else None,
        last_backup_status=row.last_backup_status,
        last_backup_error=row.last_backup_message,
    )


@router.get("/settings/backup", response_model=BackupConfigResponse)
async def get_backup_settings(
    session: AsyncSession = Depends(get_async_session),
) -> BackupConfigResponse:
    row = await _get_or_create_settings(session)
    return _settings_to_response(row)


@router.put("/settings/backup", response_model=BackupConfigResponse)
async def put_backup_settings(
    payload: BackupConfigUpdate,
    session: AsyncSession = Depends(get_async_session),
) -> BackupConfigResponse:
    row = await _get_or_create_settings(session)

    row.enabled = payload.enabled
    row.remote_url = (payload.remote_url or "").strip() or None
    row.remote_branch = (payload.branch or "main").strip() or "main"
    row.auto_backup_hours = payload.auto_backup_hours

    if "deploy_key" in payload.model_fields_set:
        deploy_key = payload.deploy_key
        if deploy_key is None or deploy_key == "":
            row.deploy_key_encrypted = None
            row.deploy_key_fingerprint = None
        else:
            row.deploy_key_encrypted = encrypt(deploy_key)
            row.deploy_key_fingerprint = fingerprint(deploy_key)
            try:
                decrypt(row.deploy_key_encrypted)
            except ValueError as exc:
                raise HTTPException(500, str(exc)) from exc

    await session.commit()
    await session.refresh(row)
    return _settings_to_response(row)


@router.post("/settings/backup/trigger", response_model=TaskAccepted, status_code=202)
async def trigger_backup(
    session: AsyncSession = Depends(get_async_session),
) -> TaskAccepted:
    row = await _get_or_create_settings(session)
    if not row.remote_url:
        raise HTTPException(400, "Backup remote URL is not configured")
    if row.deploy_key_encrypted is None:
        raise HTTPException(400, "No deploy key on file")
    task = backup_wiki.apply_async(kwargs={"manual": True}, queue="maintenance")
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


# ---------------------------------------------------------------------------
# Repositories + access control
# ---------------------------------------------------------------------------


@router.get("/repositories")
async def list_repositories(
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    rows = (
        (await session.execute(select(Repository).order_by(Repository.identifier))).scalars().all()
    )
    return {"repositories": [r.to_dict() for r in rows]}


@router.patch("/repositories/{repo_id}")
async def update_repository(
    repo_id: str,
    payload: RepositoryUpdate,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    row = (
        (await session.execute(select(Repository).where(Repository.id == repo_id)))
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(404, "Repository not found")

    if payload.access_status is not None:
        if payload.access_status not in repo_access.VALID_STATUSES:
            raise HTTPException(400, f"invalid access_status: {payload.access_status}")
        row.access_status = payload.access_status

    if payload.display_name is not None:
        row.display_name = payload.display_name.strip() or None

    if payload.auth_method is not None:
        if payload.auth_method not in repo_access.VALID_AUTH_METHODS:
            raise HTTPException(400, f"invalid auth_method: {payload.auth_method}")
        if payload.auth_method not in repo_access.IMPLEMENTED_AUTH_METHODS:
            raise HTTPException(400, f"auth_method not yet supported: {payload.auth_method}")

    # Only touch credentials when the caller explicitly sent the field.
    if "credential" in payload.model_fields_set or payload.auth_method is not None:
        method = payload.auth_method or row.auth_method
        secret = payload.credential
        repo_access.set_credential(row, method, secret)

    await session.commit()
    await session.refresh(row)
    return row.to_dict()


@router.get("/access-requests")
async def list_access_requests(
    session: AsyncSession = Depends(get_async_session),
    status: str | None = None,
) -> dict[str, Any]:
    stmt = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    if status:
        stmt = stmt.where(AccessRequest.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return {"requests": [r.to_dict() for r in rows]}


@router.post("/access-requests/{request_id}/resolve")
async def resolve_access_request(
    request_id: str,
    payload: AccessRequestResolve,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    if payload.decision not in ("approved", "denied"):
        raise HTTPException(400, "decision must be 'approved' or 'denied'")

    req = (
        (await session.execute(select(AccessRequest).where(AccessRequest.id == request_id)))
        .scalars()
        .first()
    )
    if req is None:
        raise HTTPException(404, "Access request not found")

    req.status = payload.decision
    req.resolved_at = dt.datetime.utcnow()

    # Approving a request grants the repo (creating the row if needed).
    if payload.decision == "approved":
        repo = (
            (
                await session.execute(
                    select(Repository).where(
                        Repository.provider == req.provider,
                        Repository.identifier == req.identifier,
                    )
                )
            )
            .scalars()
            .first()
        )
        if repo is None:
            repo = Repository(provider=req.provider, identifier=req.identifier)
            session.add(repo)
        repo.access_status = repo_access.ALLOWED

    await session.commit()
    await session.refresh(req)
    return req.to_dict()


# ---------------------------------------------------------------------------
# Security / egress monitoring
# ---------------------------------------------------------------------------


def _configured_external_integrations() -> list[str]:
    """External hosts Tracebow *could* reach given current configuration."""
    from tracebow.services.egress import _host_of

    hosts: list[str] = []
    seen: set[str] = set()

    def _add(url: str | None, enabled: bool) -> None:
        if not (url and enabled):
            return
        host = _host_of(url)
        if host and host not in seen and classify_host(host) == EXTERNAL:
            seen.add(host)
            hosts.append(host)

    _add(settings.github_api_base, bool(settings.github_token))
    _add(settings.jira_url, bool(settings.jira_url and settings.jira_api_token))
    _add("https://slack.com", bool(settings.slack_bot_token))
    _add(settings.jenkins_url, bool(settings.jenkins_url and settings.jenkins_api_token))
    return hosts


@router.get("/security/summary")
async def security_summary(
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    total = (await session.execute(select(func.count()).select_from(EgressEvent))).scalar_one()
    external = (
        await session.execute(
            select(func.count())
            .select_from(EgressEvent)
            .where(EgressEvent.destination_kind == EXTERNAL)
        )
    ).scalar_one()
    internal = (
        await session.execute(
            select(func.count())
            .select_from(EgressEvent)
            .where(EgressEvent.destination_kind == INTERNAL)
        )
    ).scalar_one()
    sensitive = (
        await session.execute(
            select(func.count())
            .select_from(EgressEvent)
            .where(EgressEvent.sensitive_flags.isnot(None))
        )
    ).scalar_one()
    blocked = (
        await session.execute(
            select(func.count()).select_from(EgressEvent).where(EgressEvent.blocked.is_(True))
        )
    ).scalar_one()

    dest_rows = (
        await session.execute(
            select(
                EgressEvent.destination_host,
                EgressEvent.destination_kind,
                func.count().label("count"),
                func.max(EgressEvent.created_at).label("last_seen"),
            ).group_by(EgressEvent.destination_host, EgressEvent.destination_kind)
        )
    ).all()
    destinations = [
        {
            "host": host,
            "kind": kind,
            "count": int(count),
            "last_seen": last_seen.isoformat() if last_seen is not None else None,
        }
        for host, kind, count, last_seen in dest_rows
    ]

    external_integrations = _configured_external_integrations()
    posture = (
        "external_configured" if external_integrations or int(external) > 0 else "internal_only"
    )

    return {
        "posture": posture,
        "external_integrations": external_integrations,
        "total_events": int(total),
        "external_events": int(external),
        "internal_events": int(internal),
        "sensitive_events": int(sensitive),
        "blocked_events": int(blocked),
        "destinations": destinations,
    }


@router.get("/security/egress")
async def security_egress(
    session: AsyncSession = Depends(get_async_session),
    kind: str | None = None,
    sensitive: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    stmt = select(EgressEvent).order_by(EgressEvent.created_at.desc())
    if kind in (INTERNAL, EXTERNAL):
        stmt = stmt.where(EgressEvent.destination_kind == kind)
    if sensitive:
        stmt = stmt.where(EgressEvent.sensitive_flags.isnot(None))
    stmt = stmt.limit(max(1, min(limit, 1000)))
    rows = (await session.execute(stmt)).scalars().all()
    return {"events": [e.to_dict() for e in rows]}


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


@router.get("/stacktraces/{stacktrace_id}")
async def get_stacktrace(
    stacktrace_id: str,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    row = (
        (await session.execute(select(Stacktrace).where(Stacktrace.id == stacktrace_id)))
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(404, "Stacktrace not found")
    return {
        "id": row.id,
        "failure_id": row.failure_id,
        "excerpt": row.excerpt,
        "line_count": row.line_count,
        "language": row.language,
        "full_text": row.full_text,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
