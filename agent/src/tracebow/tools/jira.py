"""Jira native tools — Atlassian Cloud REST API v3."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from tracebow.config import get_settings
from tracebow.tools._http import get_json


def _auth() -> tuple[str, str] | None:
    s = get_settings()
    if not (s.jira_url and s.jira_email and s.jira_api_token):
        return None
    return (s.jira_email, s.jira_api_token)


def _base() -> str:
    return get_settings().jira_url.rstrip("/")


@tool("search_jira_jql")
def search_jira_jql(jql: str, limit: int = 10) -> dict[str, Any]:
    """Search Jira issues with a JQL query.

    Example JQL: ``project = OPS AND text ~ "db timeout"``.
    Returns compact issue summaries (key, status, summary, assignee).
    """
    auth = _auth()
    if auth is None:
        return {"status": "not_configured", "missing": "JIRA_URL/JIRA_EMAIL/JIRA_API_TOKEN"}

    result = get_json(
        f"{_base()}/rest/api/3/search",
        params={
            "jql": jql,
            "maxResults": max(1, min(limit, 50)),
            "fields": "summary,status,assignee,issuetype,resolution,updated",
        },
        auth=auth,
    )
    if result.get("status") != "ok":
        return result
    issues = (result["data"] or {}).get("issues", [])
    return {
        "status": "ok",
        "jql": jql,
        "total": (result["data"] or {}).get("total", len(issues)),
        "issues": [_slim_issue(i) for i in issues],
    }


@tool("get_jira_issue")
def get_jira_issue(issue_key: str) -> dict[str, Any]:
    """Fetch a single Jira issue (summary, description, resolution, comments)."""
    auth = _auth()
    if auth is None:
        return {"status": "not_configured", "missing": "JIRA_URL/JIRA_EMAIL/JIRA_API_TOKEN"}
    result = get_json(
        f"{_base()}/rest/api/3/issue/{issue_key}",
        params={"fields": "summary,status,description,resolution,comment,issuetype"},
        auth=auth,
    )
    if result.get("status") != "ok":
        return result
    return {"status": "ok", "issue": _slim_issue(result["data"])}


def _slim_issue(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    return {
        "key": issue.get("key"),
        "summary": fields.get("summary"),
        "status": ((fields.get("status") or {}).get("name")),
        "issuetype": ((fields.get("issuetype") or {}).get("name")),
        "resolution": ((fields.get("resolution") or {}).get("name")),
        "assignee": ((fields.get("assignee") or {}).get("displayName")),
        "updated": fields.get("updated"),
    }
