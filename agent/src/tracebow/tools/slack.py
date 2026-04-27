"""Slack native tool — Web API search."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from tracebow.config import get_settings
from tracebow.tools._http import get_json


@tool("search_slack")
def search_slack(query: str, channel: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Search Slack messages for historical tribal knowledge.

    ``query`` accepts Slack's search operators (for example
    ``from:@alice "db timeout"``). ``channel`` can narrow to a single
    channel name or id.
    """
    token = get_settings().slack_bot_token
    if not token:
        return {"status": "not_configured", "missing": "SLACK_BOT_TOKEN"}

    search_query = query
    if channel:
        search_query = f"in:{channel} {query}"

    result = get_json(
        "https://slack.com/api/search.messages",
        params={"query": search_query, "count": max(1, min(limit, 50))},
        headers={"Authorization": f"Bearer {token}"},
    )
    if result.get("status") != "ok":
        return result

    data = result["data"] or {}
    if not data.get("ok", False):
        return {"status": "error", "error": data.get("error", "slack api error")}

    matches = ((data.get("messages") or {}).get("matches")) or []
    return {
        "status": "ok",
        "query": search_query,
        "total": (data.get("messages") or {}).get("total", len(matches)),
        "matches": [
            {
                "channel": (m.get("channel") or {}).get("name"),
                "user": m.get("username") or m.get("user"),
                "text": m.get("text"),
                "ts": m.get("ts"),
                "permalink": m.get("permalink"),
            }
            for m in matches
        ],
    }
