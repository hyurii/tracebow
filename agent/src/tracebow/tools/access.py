"""Access-request tool — lets the agent ask a human for repo access.

When reasoning reveals that Tracebow needs to reach a repository or CI job it
is not yet allowed to call, the agent invokes this tool. It opens a pending
:class:`~tracebow.db.AccessRequest` that a human approves in the portal — the
agent never grants itself access.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from tracebow.services.repo_access import request_access_sync


@tool("request_access")
def request_access(provider: str, identifier: str, reason: str) -> dict[str, Any]:
    """Request human approval to access a repository or CI job.

    Use this when you need data from a source Tracebow cannot currently reach
    (a GitHub repo, a Jenkins job). ``provider`` is ``github`` or ``jenkins``;
    ``identifier`` is the ``owner/repo`` or the Jenkins job name; ``reason``
    explains why the access is needed. Returns whether a request was opened.
    """
    return request_access_sync(provider, identifier, reason=reason)
