"""Tracebow API routes for webhooks and agent interaction."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from tracebow.agent import run_rca_agent
from tracebow.config import settings

router = APIRouter(prefix="/api/v1", tags=["api"])


# --- Webhook payload models ---


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

    repository: str = Field(
        ..., description="Repository full name (org/repo)",
    )
    pr_number: str | None = Field(
        None, description="Pull request number",
    )
    job_name: str = Field(
        "unknown-job", description="CI job name",
    )
    build_url: str | None = Field(
        None, description="URL to the failing build",
    )
    log_content: str = Field(
        ..., description="Raw build log content",
    )


class RCAResponse(BaseModel):
    """Response from RCA agent."""

    success: bool
    job_or_repo: str
    build_or_run_id: str | int
    root_cause_summary: str | None
    recommendations: list[str]
    related_tickets: list[str]
    related_slack_threads: list[str]
    blast_radius: list[str]
    processing_time_seconds: float


# --- CLI ingestion endpoint ---


@router.post("/analyze", response_model=dict)
async def analyze_from_cli(
    payload: CLIAnalyzePayload,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """
    Receive a build log from the Go CLI agent.
    Accepts the log inline and kicks off async RCA.
    """
    task_id = f"cli-{payload.repository.replace('/', '-')}-{payload.job_name}"
    background_tasks.add_task(
        _run_cli_rca,
        repository=payload.repository,
        pr_number=payload.pr_number,
        job_name=payload.job_name,
        build_url=payload.build_url,
        log_content=payload.log_content,
    )
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": (
            "RCA analysis started. "
            f"Query /api/v1/failures/{task_id}/rca for results."
        ),
    }


# --- Webhook endpoints ---


@router.post("/webhooks/jenkins", response_model=dict)
async def jenkins_webhook(
    payload: JenkinsWebhookPayload,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """
    Receive Jenkins build failure notification.
    Triggers async RCA analysis; returns immediately with task ID.
    """
    if not settings.jenkins_url:
        raise HTTPException(503, "Jenkins integration not configured (JENKINS_URL)")

    task_id = f"jenkins-{payload.job_name}-{payload.build_number}"
    background_tasks.add_task(
        _run_jenkins_rca,
        job_name=payload.job_name,
        build_number=payload.build_number,
        git_commit=payload.git_commit,
        git_branch=payload.git_branch,
        console_url=payload.console_url,
        build_url=payload.build_url,
    )
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "RCA analysis started. Query /api/v1/rca/{task_id} for results.",
    }


@router.post("/webhooks/github", response_model=dict)
async def github_webhook(
    payload: GitHubWebhookPayload,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """
    Receive GitHub Actions workflow failure notification.
    Triggers async RCA analysis.
    """
    # GitHub token needed for fetching workflow logs; webhook can be accepted without it
    if not settings.github_token:
        raise HTTPException(503, "GitHub integration not configured (GITHUB_TOKEN)")

    task_id = f"github-{payload.repository.replace('/', '-')}-{payload.run_id}"
    background_tasks.add_task(
        _run_github_rca,
        repository=payload.repository,
        run_id=payload.run_id,
        head_sha=payload.head_sha,
        head_branch=payload.head_branch,
        pr_number=payload.pull_request_number,
        workflow_name=payload.workflow_name,
        run_url=payload.run_url,
    )
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "RCA analysis started. Query /api/v1/rca/{task_id} for results.",
    }


# --- Synchronous RCA (for chat / manual trigger) ---


class RCARequest(BaseModel):
    """Request for on-demand RCA or chat."""

    source: str = Field(..., description="jenkins | github")
    job_name_or_repo: str
    build_number_or_run_id: int | str
    additional_context: str | None = None


class ChatRequest(BaseModel):
    """Chat message to the agent."""

    message: str
    context: dict[str, Any] | None = None


@router.post("/rca", response_model=RCAResponse)
async def trigger_rca(request: RCARequest) -> RCAResponse:
    """Trigger synchronous RCA analysis."""
    result = await _run_rca_sync(
        source=request.source,
        job_or_repo=request.job_name_or_repo,
        build_or_run_id=request.build_number_or_run_id,
        additional_context=request.additional_context,
    )
    return result


@router.get("/failures", response_model=dict)
async def list_failures() -> dict[str, Any]:
    """List recent pipeline failures (placeholder; in production, query graph/DB)."""
    return {"failures": []}


@router.get("/failures/{task_id}/rca", response_model=dict)
async def get_failure_rca(task_id: str) -> dict[str, Any]:
    """Get RCA summary for a failure task (placeholder; in production, query store)."""
    return {"task_id": task_id, "summary": None, "status": "not_found"}


@router.post("/chat", response_model=dict)
async def chat_with_agent(request: ChatRequest) -> dict[str, Any]:
    """Send a message to the RCA agent and get a response."""
    response = await run_rca_agent(
        query=request.message,
        context=request.context or {},
    )
    return {"response": response, "context_used": bool(request.context)}


# --- Background and sync RCA execution ---


async def _run_jenkins_rca(
    job_name: str,
    build_number: int,
    git_commit: str | None,
    git_branch: str | None,
    console_url: str | None,
    build_url: str | None,
) -> None:
    """Background task: run RCA for Jenkins failure."""
    await _run_rca_sync(
        source="jenkins",
        job_or_repo=job_name,
        build_or_run_id=build_number,
        additional_context={
            "git_commit": git_commit,
            "git_branch": git_branch,
            "console_url": console_url,
            "build_url": build_url,
        },
    )
    # Results are stored in graph/vector; could be pushed to Slack/Jira via MCP
    return None


async def _run_github_rca(
    repository: str,
    run_id: int,
    head_sha: str | None,
    head_branch: str | None,
    pr_number: int | None,
    workflow_name: str | None,
    run_url: str | None,
) -> None:
    """Background task: run RCA for GitHub Actions failure."""
    await _run_rca_sync(
        source="github",
        job_or_repo=repository,
        build_or_run_id=run_id,
        additional_context={
            "head_sha": head_sha,
            "head_branch": head_branch,
            "pr_number": pr_number,
            "workflow_name": workflow_name,
            "run_url": run_url,
        },
    )
    return None


async def _run_cli_rca(
    repository: str,
    pr_number: str | None,
    job_name: str,
    build_url: str | None,
    log_content: str,
) -> None:
    """Background task: run RCA for logs sent by the Go CLI agent."""
    await _run_rca_sync(
        source="cli",
        job_or_repo=repository,
        build_or_run_id=job_name,
        additional_context={
            "pr_number": pr_number,
            "build_url": build_url,
            "log_content": log_content,
        },
    )


async def _run_rca_sync(
    source: str,
    job_or_repo: str,
    build_or_run_id: int | str,
    additional_context: dict[str, Any] | None = None,
) -> RCAResponse:
    """Execute RCA and return structured response."""
    import time

    start = time.perf_counter()
    result = await run_rca_agent(
        query=f"Analyze root cause for {source} failure: {job_or_repo} build/run {build_or_run_id}",
        context={
            "source": source,
            "job_or_repo": job_or_repo,
            "build_or_run_id": build_or_run_id,
            **(additional_context or {}),
        },
    )
    elapsed = time.perf_counter() - start

    # Parse structured fields from agent output (simplified)
    return RCAResponse(
        success=True,
        job_or_repo=job_or_repo,
        build_or_run_id=build_or_run_id,
        root_cause_summary=result,
        recommendations=[],
        related_tickets=[],
        related_slack_threads=[],
        blast_radius=[],
        processing_time_seconds=round(elapsed, 2),
    )
