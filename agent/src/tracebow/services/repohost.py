"""Fetch the latest failing change (diff) from a provider.

Deliberately narrow: we grab only the *latest* diff (the failing PR or commit)
rather than cloning/indexing the whole repo. Only GitHub is supported today;
Jenkins diffs are deferred. Credentials come from the per-repo grant when set,
falling back to the global ``GITHUB_TOKEN``.
"""

from __future__ import annotations

import logging
from typing import Any

from tracebow.config import get_settings
from tracebow.services import repo_access
from tracebow.tools._http import get_json

logger = logging.getLogger(__name__)

# Cap stored patch size to keep Postgres rows sane; flag when we trim.
MAX_PATCH_CHARS = 60_000


def _github_token(identifier: str) -> str | None:
    cred = repo_access.get_credential_sync("github", identifier)
    if cred is not None and cred[0] == "github_pat" and cred[1]:
        return cred[1]
    return get_settings().github_token or None


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _assemble_patch(files: list[dict[str, Any]]) -> tuple[str, int, int, int]:
    chunks: list[str] = []
    additions = 0
    deletions = 0
    for f in files:
        additions += int(f.get("additions") or 0)
        deletions += int(f.get("deletions") or 0)
        patch = f.get("patch")
        header = f"diff --- {f.get('filename')} ({f.get('status')})"
        chunks.append(header if not patch else f"{header}\n{patch}")
    return "\n\n".join(chunks), len(files), additions, deletions


def fetch_latest_diff(
    provider: str, identifier: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    """Return a diff dict for the failing change, or ``None`` if unavailable."""
    if provider != "github":
        return None
    if "/" not in identifier:
        return None

    token = _github_token(identifier)
    if not token:
        return None

    owner, _, repo = identifier.partition("/")
    base = get_settings().github_api_base.rstrip("/")
    headers = _github_headers(token)

    pr_number = payload.get("pull_request_number") or payload.get("pr_number")
    commit = payload.get("commit_sha") or payload.get("git_commit") or payload.get("head_sha")

    files: list[dict[str, Any]] = []
    ref: str | None = None

    if pr_number:
        ref = f"PR #{pr_number}"
        result = get_json(
            f"{base}/repos/{owner}/{repo}/pulls/{pr_number}/files",
            headers=headers,
            params={"per_page": 50},
            purpose="fetch_latest_diff",
        )
        if result.get("status") == "ok" and isinstance(result.get("data"), list):
            files = result["data"]
    elif commit:
        ref = str(commit)[:40]
        result = get_json(
            f"{base}/repos/{owner}/{repo}/commits/{commit}",
            headers=headers,
            purpose="fetch_latest_diff",
        )
        if result.get("status") == "ok" and isinstance(result.get("data"), dict):
            files = result["data"].get("files") or []
    else:
        return None

    if not files:
        return None

    patch, files_changed, additions, deletions = _assemble_patch(files)
    truncated = len(patch) > MAX_PATCH_CHARS
    if truncated:
        patch = patch[:MAX_PATCH_CHARS] + "\n... (truncated)"

    return {
        "provider": provider,
        "ref": ref,
        "files_changed": files_changed,
        "additions": additions,
        "deletions": deletions,
        "patch": patch,
        "truncated": truncated,
    }
