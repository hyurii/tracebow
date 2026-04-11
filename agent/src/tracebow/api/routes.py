"""Tracebow API routes — thin layer that validates and enqueues work to Celery."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tracebow.celery_app import app as celery_app
from tracebow.config import settings
from tracebow.tasks import run_chat, run_cli_rca, run_github_rca, run_jenkins_rca, run_rca

router = APIRouter(prefix="/api/v1", tags=["api"])


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class JenkinsWebhookPayload(BaseModel):
    """Payload from Jenkins pipeline post block."""

    job_name: str = Field(..., description="Jenkins job name")
    build_number: int = Field(..., description="Build number")
    git_commit: str | None = Field(None, description="Git commit SHA")
    git_branch: str | None = Field(None, description="Git branch")
    workspace_path: str | None = Field(None, description="Workspace path")
    console_url: str | None = Field(None, description="URL to raw console output")
    build_url: str | None = Field(None, description="Jenkins build URL")
    cause: str | None = Field(None, description="Failure cause summary")


class GitHubWebhookPayload(BaseModel):
    """Payload from GitHub Actions workflow_run webhook."""

    repository: str = Field(..., description="Repository full name (owner/repo)")
    run_id: int = Field(..., description="Workflow run ID")
    run_url: str | None = Field(None, description="Workflow run URL")
    head_sha: str | None = Field(None, description="Commit SHA for the run")
    head_branch: str | None = Field(None, description="Branch name")
    pull_request_number: int | None = Field(None, description="PR number if triggered by PR")
    workflow_name: str | None = Field(None, description="Name of the workflow")
    event: str | None = Field(None, description="GitHub event type")


class CLIAnalyzePayload(BaseModel):
    """Payload from the Go CLI agent (tracebow-cli)."""

    repository: str = Field(..., description="Repository full name (org/repo)")
    pr_number: str | None = Field(None, description="Pull request number")
    job_name: str = Field("unknown-job", description="CI job name")
    build_url: str | None = Field(None, description="URL to the failing build")
    log_content: str = Field(..., description="Raw build log content")


class RCARequest(BaseModel):
    """Request for on-demand RCA."""

    source: str = Field(..., description="jenkins | github")
    job_name_or_repo: str
    build_number_or_run_id: int | str
    additional_context: str | None = None


class ChatRequest(BaseModel):
    """Chat message to the agent."""

    message: str
    context: dict[str, Any] | None = None


class TaskAccepted(BaseModel):
    """Returned by every endpoint that enqueues work."""

    status: str = "accepted"
    task_id: str
    poll_url: str


class TaskStatusResponse(BaseModel):
    """Returned by the task-polling endpoint."""

    task_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# CLI ingestion
# ---------------------------------------------------------------------------


@router.post("/analyze", response_model=TaskAccepted, status_code=202)
async def analyze_from_cli(payload: CLIAnalyzePayload) -> TaskAccepted:
    """
    Receive a build log from the Go CLI agent.
    Enqueues an RCA task and returns immediately.
    """
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


# ---------------------------------------------------------------------------
# Webhook endpoints
# ---------------------------------------------------------------------------


@router.post("/webhooks/jenkins", response_model=TaskAccepted, status_code=202)
async def jenkins_webhook(payload: JenkinsWebhookPayload) -> TaskAccepted:
    """Receive Jenkins build failure notification."""
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
        priority=8,  # production webhooks get high priority
    )
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


@router.post("/webhooks/github", response_model=TaskAccepted, status_code=202)
async def github_webhook(payload: GitHubWebhookPayload) -> TaskAccepted:
    """Receive GitHub Actions workflow failure notification."""
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
        priority=8,
    )
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


# ---------------------------------------------------------------------------
# On-demand RCA + Chat (both async via Celery now)
# ---------------------------------------------------------------------------


@router.post("/rca", response_model=TaskAccepted, status_code=202)
async def trigger_rca(request: RCARequest) -> TaskAccepted:
    """Enqueue an on-demand RCA analysis."""
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

    task = run_rca.apply_async(
        args=[request.source, payload],
        queue="rca",
    )
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


@router.post("/chat", response_model=TaskAccepted, status_code=202)
async def chat_with_agent(request: ChatRequest) -> TaskAccepted:
    """Send a message to the RCA agent (processed asynchronously)."""
    task = run_chat.apply_async(
        kwargs={"message": request.message, "context": request.context},
        queue="rca",
    )
    return TaskAccepted(task_id=task.id, poll_url=f"/api/v1/tasks/{task.id}")


# ---------------------------------------------------------------------------
# Task status polling
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """
    Poll task status.  Clients call this until status is SUCCESS or FAILURE.

    Status values: PENDING, STARTED, RETRY, SUCCESS, FAILURE.
    """
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)
    response = TaskStatusResponse(task_id=task_id, status=result.status)

    if result.ready():
        if result.successful():
            response.result = result.result
        else:
            response.error = str(result.result)

    return response


@router.get("/failures", response_model=dict)
async def list_failures() -> dict[str, Any]:
    """List recent pipeline failures (placeholder; in production, query graph/DB)."""
    return {"failures": []}
