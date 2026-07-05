"""Native LangGraph ``@tool`` decorators.

Each module here exposes one or more tools that the LangGraph orchestrator
binds onto the LLM. No MCP, no protocol translation — just Python
functions with docstrings.

Design notes:
* Tools return ``dict`` so the LLM sees structured JSON.
* Tools NEVER raise; failures come back as ``{"status": "error", ...}``.
* Integrations that require credentials report
  ``{"status": "not_configured"}`` rather than erroring, so the graph
  can gracefully continue with what it has.
"""

from tracebow.tools.access import request_access
from tracebow.tools.github import get_github_commit, get_github_pr_files, list_github_runs
from tracebow.tools.jenkins import fetch_jenkins_console, list_jenkins_builds
from tracebow.tools.jira import get_jira_issue, search_jira_jql
from tracebow.tools.slack import search_slack
from tracebow.tools.wiki import read_wiki, search_wiki, write_wiki

ALL_TOOLS = [
    search_wiki,
    read_wiki,
    write_wiki,
    fetch_jenkins_console,
    list_jenkins_builds,
    get_github_commit,
    get_github_pr_files,
    list_github_runs,
    search_jira_jql,
    get_jira_issue,
    search_slack,
    request_access,
]

__all__ = [
    "ALL_TOOLS",
    "fetch_jenkins_console",
    "get_github_commit",
    "get_github_pr_files",
    "get_jira_issue",
    "list_github_runs",
    "list_jenkins_builds",
    "read_wiki",
    "request_access",
    "search_jira_jql",
    "search_slack",
    "search_wiki",
    "write_wiki",
]
