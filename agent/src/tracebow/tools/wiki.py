"""Wiki tools — the LLM's only path to the knowledge base."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from tracebow.services.wiki import WikiError, WikiService

logger = logging.getLogger(__name__)


def _svc() -> WikiService:
    return WikiService()


@tool("search_wiki")
def search_wiki(query: str, limit: int = 5) -> dict[str, Any]:
    """Search the company wiki for runbooks or policy notes matching ``query``.

    Returns a ranked list of hits with path, title, excerpt, and score.
    Use this as the FIRST step for any novel failure — the wiki contains
    company-approved fixes that override any generic reasoning.
    """
    try:
        hits = _svc().search(query, limit=limit)
    except WikiError as exc:
        logger.warning("search_wiki failed: %s", exc)
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "query": query,
        "hits": [
            {
                "path": h.path,
                "title": h.title,
                "excerpt": h.excerpt,
                "score": h.score,
            }
            for h in hits
        ],
    }


@tool("read_wiki")
def read_wiki(path: str) -> dict[str, Any]:
    """Read a single Markdown document from the wiki.

    ``path`` must be the repo-relative path returned by ``search_wiki``
    (for example ``runbooks/db_timeout.md``).
    """
    try:
        doc = _svc().read(path)
    except WikiError as exc:
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "path": doc.path,
        "title": doc.title,
        "content": doc.content,
        "size": doc.size,
    }


@tool("write_wiki")
def write_wiki(path: str, content: str, message: str | None = None) -> dict[str, Any]:
    """Create or update a Markdown runbook.

    Use this ONLY after reasoning out a fix for a novel failure, so the
    next similar failure hits the fast path. ``path`` should live under
    ``runbooks/`` and end in ``.md``. ``content`` must be full Markdown
    (including ``# Title``). ``message`` is an optional commit message.
    """
    try:
        result = _svc().write(path, content, message=message)
    except WikiError as exc:
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "path": result.path,
        "created": result.created,
        "commit_sha": result.commit_sha,
    }
