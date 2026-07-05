"""Jenkins native tools — direct REST API calls."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from tracebow.config import get_settings
from tracebow.tools._http import get_json


def _auth() -> tuple[str, str] | None:
    s = get_settings()
    if not (s.jenkins_url and s.jenkins_user and s.jenkins_api_token):
        return None
    return (s.jenkins_user, s.jenkins_api_token)


def _base() -> str:
    return get_settings().jenkins_url.rstrip("/")


@tool("fetch_jenkins_console")
def fetch_jenkins_console(job_name: str, build_number: int, tail: int = 200) -> dict[str, Any]:
    """Fetch the console log of a Jenkins build.

    ``tail`` caps how many trailing lines are returned (defaults to 200)
    to keep the LLM's context small.
    """
    auth = _auth()
    if auth is None:
        return {"status": "not_configured", "missing": "JENKINS_URL/JENKINS_USER/JENKINS_API_TOKEN"}

    url = f"{_base()}/job/{job_name}/{build_number}/consoleText"
    result = get_json(url, auth=auth)
    if result.get("status") != "ok":
        return result

    text = result["data"] if isinstance(result["data"], str) else str(result["data"])
    lines = text.splitlines()
    excerpt = "\n".join(lines[-max(1, tail) :])
    return {
        "status": "ok",
        "job_name": job_name,
        "build_number": build_number,
        "total_lines": len(lines),
        "excerpt": excerpt,
    }


@tool("list_jenkins_builds")
def list_jenkins_builds(job_name: str, limit: int = 10) -> dict[str, Any]:
    """List the most recent builds for a Jenkins job with their results."""
    auth = _auth()
    if auth is None:
        return {"status": "not_configured", "missing": "JENKINS_URL/JENKINS_USER/JENKINS_API_TOKEN"}
    url = f"{_base()}/job/{job_name}/api/json"
    result = get_json(
        url,
        auth=auth,
        params={"tree": f"builds[number,result,timestamp,url]{{0,{max(1, limit)}}}"},
    )
    if result.get("status") != "ok":
        return result
    builds = (result["data"] or {}).get("builds", [])
    return {"status": "ok", "job_name": job_name, "builds": builds}
