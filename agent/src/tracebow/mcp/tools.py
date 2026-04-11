"""
MCP Tool Registry - Defines the suite of tools available to the agentic engine.

The LLM receives these tools and can invoke them dynamically during RCA.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class MCPTool:
    """Definition of an MCP-compatible tool."""

    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]


class MCPToolRegistry:
    """
    Registry of MCP tools for Jenkins, GitHub, Jira, and Slack.
    The agent uses these tools to dynamically navigate infrastructure.
    """

    def __init__(self):
        self._tools: dict[str, MCPTool] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register built-in MCP tools."""
        self.register(
            MCPTool(
                name="fetch_jenkins_console_output",
                description=(
                    "Fetch raw console output from a Jenkins build. "
                    "Use when analyzing pipeline failures."
                ),
                parameters={
                    "job_name": {"type": "string", "description": "Jenkins job name"},
                    "build_number": {"type": "integer", "description": "Build number"},
                },
                handler=self._fetch_jenkins_console,
            )
        )
        self.register(
            MCPTool(
                name="query_jira_jql",
                description=(
                    "Search Jira issues using JQL. Use to find similar past incidents or RCAs."
                ),
                parameters={
                    "jql": {"type": "string", "description": "Jira Query Language query"},
                    "max_results": {"type": "integer", "description": "Max results (default 10)"},
                },
                handler=self._query_jira,
            )
        )
        self.register(
            MCPTool(
                name="get_github_commit_diff",
                description=(
                    "Fetch the diff of a GitHub commit. "
                    "Use to correlate code changes with failures."
                ),
                parameters={
                    "owner": {"type": "string", "description": "Repository owner"},
                    "repo": {"type": "string", "description": "Repository name"},
                    "commit_sha": {"type": "string", "description": "Commit SHA"},
                },
                handler=self._get_github_diff,
            )
        )
        self.register(
            MCPTool(
                name="get_github_pr_changes",
                description="Fetch files changed in a pull request.",
                parameters={
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "pr_number": {"type": "integer"},
                },
                handler=self._get_github_pr_changes,
            )
        )
        self.register(
            MCPTool(
                name="search_slack_archive",
                description=(
                    "Search Slack channel history for keywords. "
                    "Use to find tribal knowledge about errors."
                ),
                parameters={
                    "keyword": {"type": "string"},
                    "channel": {"type": "string", "description": "Channel ID or name"},
                    "date_from": {"type": "string", "description": "ISO date"},
                    "date_to": {"type": "string", "description": "ISO date"},
                },
                handler=self._search_slack,
            )
        )
        self.register(
            MCPTool(
                name="search_semantic_logs",
                description=(
                    "Semantic search over indexed log chunks, Jira, and Slack. "
                    "Use for cross-tool correlation."
                ),
                parameters={
                    "query": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter: logs, jira, slack",
                    },
                    "limit": {"type": "integer", "description": "Max results (default 10)"},
                },
                handler=self._search_semantic,
            )
        )
        self.register(
            MCPTool(
                name="get_blast_radius",
                description=(
                    "Get upstream/downstream repositories and artifacts affected by a change."
                ),
                parameters={
                    "repo": {"type": "string"},
                    "commit_sha": {"type": "string"},
                },
                handler=self._get_blast_radius,
            )
        )

    def register(self, tool: MCPTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get_tools(self) -> list[dict]:
        """Return tool schemas for LLM consumption (OpenAI function calling format)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        "type": "object",
                        "properties": t.parameters,
                        "required": list(t.parameters.keys()),
                    },
                },
            }
            for t in self._tools.values()
        ]

    async def invoke(self, name: str, **kwargs: Any) -> Any:
        """Invoke a tool by name."""
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return await tool.handler(**kwargs)

    # --- Tool implementations (stubs; replaced by injected services at runtime) ---

    async def _fetch_jenkins_console(self, job_name: str, build_number: int) -> dict:
        # Injected: use Jenkins API client
        return {
            "status": "stub",
            "message": "Implement via JENKINS_URL + token",
            "job_name": job_name,
            "build_number": build_number,
        }

    async def _query_jira(self, jql: str, max_results: int = 10) -> dict:
        return {
            "status": "stub",
            "message": "Implement via Jira REST API",
            "jql": jql,
        }

    async def _get_github_diff(self, owner: str, repo: str, commit_sha: str) -> dict:
        return {
            "status": "stub",
            "message": "Implement via GitHub API",
            "owner": owner,
            "repo": repo,
            "commit_sha": commit_sha,
        }

    async def _get_github_pr_changes(self, owner: str, repo: str, pr_number: int) -> dict:
        return {
            "status": "stub",
            "message": "Implement via GitHub API",
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
        }

    async def _search_slack(self, keyword: str, channel: str, date_from: str, date_to: str) -> dict:
        return {
            "status": "stub",
            "message": "Implement via Slack API",
            "keyword": keyword,
        }

    async def _search_semantic(
        self, query: str, sources: list[str] | None = None, limit: int = 10
    ) -> dict:
        return {
            "status": "stub",
            "message": "Implement via RetrievalService",
            "query": query,
        }

    async def _get_blast_radius(self, repo: str, commit_sha: str) -> dict:
        return {
            "status": "stub",
            "message": "Implement via GraphService",
            "repo": repo,
            "commit_sha": commit_sha,
        }
