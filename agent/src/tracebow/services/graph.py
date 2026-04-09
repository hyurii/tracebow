"""
Graph Service - Neo4j-backed Graph RAG for blast radius mapping.

Models:
- Repositories, PRs, commits, Jira tickets, Slack threads as nodes
- Relationships: imports, resolves, references, etc.
"""

from __future__ import annotations

from typing import Any

try:
    from neo4j import AsyncGraphDatabase
except ImportError:
    AsyncGraphDatabase = None


class GraphService:
    """
    Knowledge graph for cross-repository dependency and lineage.
    """

    def __init__(
        self,
        uri: str = "bolt://neo4j:7687",
        user: str = "neo4j",
        password: str = "tracebow",
    ):
        self._uri = uri
        self._user = user
        self._password = password
        self._driver = None

    def _get_driver(self):
        if AsyncGraphDatabase is None:
            return None
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
            )
        return self._driver

    async def ensure_schema(self) -> None:
        """Create indexes and constraints."""
        driver = self._get_driver()
        if not driver:
            return
        async with driver.session() as session:
            await session.run(
                "CREATE INDEX repo_name IF NOT EXISTS FOR (r:Repo) ON (r.name)"
            )
            await session.run(
                "CREATE INDEX commit_sha IF NOT EXISTS FOR (c:Commit) ON (c.sha)"
            )

    async def get_blast_radius(
        self,
        repo: str,
        commit_sha: str,
        direction: str = "BOTH",
        depth: int = 3,
    ) -> dict[str, Any]:
        """
        Traverse graph to find upstream/downstream affected repositories.
        """
        driver = self._get_driver()
        if not driver:
            return {
                "status": "unavailable",
                "message": "Neo4j driver not installed or not configured",
                "repo": repo,
                "commit_sha": commit_sha,
            }

        # Try graph traversal first; fallback to simple commit lookup
        query_traverse = """
        MATCH path = (c:Commit)-[:AFFECTS*1..%d]-(node)
        WHERE c.sha = $sha AND c.repo = $repo
        RETURN DISTINCT labels(node)[0] AS type, node.name AS name, node.repo AS repo
        LIMIT 50
        """ % depth
        query_fallback = """
        MATCH (c:Commit) WHERE c.sha = $sha AND c.repo = $repo
        RETURN 'Commit' AS type, c.sha AS name, c.repo AS repo
        LIMIT 1
        """

        async with driver.session() as session:
            try:
                result = await session.run(query_traverse, sha=commit_sha, repo=repo)
                rows = await result.data()
                if not rows:
                    result = await session.run(query_fallback, sha=commit_sha, repo=repo)
                    rows = await result.data()
            except Exception:
                result = await session.run(query_fallback, sha=commit_sha, repo=repo)
                rows = await result.data()

        return {
            "status": "ok",
            "repo": repo,
            "commit_sha": commit_sha,
            "affected": rows,
        }

    async def add_repo_dependency(
        self,
        repo_from: str,
        repo_to: str,
        relation: str = "DEPENDS_ON",
    ) -> None:
        """Record that repo_from depends on repo_to."""
        driver = self._get_driver()
        if not driver:
            return
        async with driver.session() as session:
            await session.run(
                """
                MERGE (a:Repo {name: $from})
                MERGE (b:Repo {name: $to})
                MERGE (a)-[r:DEPENDS_ON]->(b)
                """,
                **{"from": repo_from, "to": repo_to},
            )

    async def add_commit(
        self,
        repo: str,
        sha: str,
        message: str | None = None,
        pr_number: int | None = None,
    ) -> None:
        """Add or update a commit node."""
        driver = self._get_driver()
        if not driver:
            return
        async with driver.session() as session:
            await session.run(
                """
                MERGE (c:Commit {sha: $sha, repo: $repo})
                SET c.message = $message, c.pr_number = $pr_number
                """,
                sha=sha,
                repo=repo,
                message=message or "",
                pr_number=pr_number,
            )

    async def link_commit_to_ticket(self, commit_sha: str, repo: str, ticket_key: str) -> None:
        """Link a commit to a Jira ticket."""
        driver = self._get_driver()
        if not driver:
            return
        async with driver.session() as session:
            await session.run(
                """
                MATCH (c:Commit {sha: $sha, repo: $repo})
                MERGE (t:JiraTicket {key: $key})
                MERGE (c)-[:RESOLVES]->(t)
                """,
                sha=commit_sha,
                repo=repo,
                key=ticket_key,
            )

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
