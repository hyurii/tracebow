"""GitHub native tools — direct REST API calls, no SDK."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from tracebow.config import get_settings
from tracebow.tools._http import get_json


def _auth_headers() -> dict[str, str] | None:
    token = get_settings().github_token
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _base_url() -> str:
    return get_settings().github_api_base.rstrip("/")


@tool("get_github_commit")
def get_github_commit(owner: str, repo: str, sha: str) -> dict[str, Any]:
    """Fetch commit metadata (message, author, files touched) for a SHA.

    Use when correlating a CI failure with a specific code change.
    """
    headers = _auth_headers()
    if headers is None:
        return {"status": "not_configured", "missing": "GITHUB_TOKEN"}
    result = get_json(
        f"{_base_url()}/repos/{owner}/{repo}/commits/{sha}",
        headers=headers,
    )
    return _slim_commit(result)


@tool("get_github_pr_files")
def get_github_pr_files(owner: str, repo: str, pr_number: int) -> dict[str, Any]:
    """Fetch the list of files changed in a pull request (up to 50)."""
    headers = _auth_headers()
    if headers is None:
        return {"status": "not_configured", "missing": "GITHUB_TOKEN"}
    result = get_json(
        f"{_base_url()}/repos/{owner}/{repo}/pulls/{pr_number}/files",
        headers=headers,
        params={"per_page": 50},
    )
    if result.get("status") != "ok":
        return result
    files = result["data"]
    return {
        "status": "ok",
        "count": len(files) if isinstance(files, list) else 0,
        "files": [
            {
                "filename": f.get("filename"),
                "status": f.get("status"),
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
            }
            for f in (files if isinstance(files, list) else [])
        ],
    }


@tool("list_github_runs")
def list_github_runs(owner: str, repo: str, limit: int = 10) -> dict[str, Any]:
    """List recent GitHub Actions workflow runs for a repository."""
    headers = _auth_headers()
    if headers is None:
        return {"status": "not_configured", "missing": "GITHUB_TOKEN"}
    result = get_json(
        f"{_base_url()}/repos/{owner}/{repo}/actions/runs",
        headers=headers,
        params={"per_page": max(1, min(limit, 100))},
    )
    if result.get("status") != "ok":
        return result
    runs = (result["data"] or {}).get("workflow_runs", [])
    return {
        "status": "ok",
        "runs": [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "conclusion": r.get("conclusion"),
                "status": r.get("status"),
                "head_sha": r.get("head_sha"),
                "html_url": r.get("html_url"),
                "created_at": r.get("created_at"),
            }
            for r in runs
        ],
    }


def _slim_commit(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "ok":
        return result
    commit = result["data"] or {}
    files = commit.get("files") or []
    return {
        "status": "ok",
        "sha": commit.get("sha"),
        "message": (commit.get("commit") or {}).get("message"),
        "author": ((commit.get("commit") or {}).get("author") or {}).get("name"),
        "files": [{"filename": f.get("filename"), "status": f.get("status")} for f in files[:25]],
        "html_url": commit.get("html_url"),
    }
