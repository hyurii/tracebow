"""GitHub PR, commit, and workflow run ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tracebow.ingestion.base import IngestionPipeline, RawDocument

if TYPE_CHECKING:
    from tracebow.services.embeddings import EmbeddingService


@dataclass
class GitHubChunk(RawDocument):
    """GitHub PR, commit, or workflow chunk."""

    repo: str
    pr_number: int | None
    commit_sha: str | None
    workflow_run_id: int | None
    event_type: str  # pr|commit|workflow


class GitHubIngestionPipeline(IngestionPipeline[GitHubChunk]):
    """Ingests GitHub PRs, commits, and workflow runs."""

    def parse(self, raw: dict) -> list[GitHubChunk]:
        """Parse GitHub webhook or API payload into chunks."""
        event = raw.get("event_type", "pr")
        repo = raw.get("repository", {}).get("full_name", raw.get("repo", "unknown/repo"))
        chunks: list[GitHubChunk] = []

        if event == "pull_request" or "pull_request" in raw:
            pr_data = raw.get("pull_request", raw)
            pr_number = pr_data.get("number")
            title = pr_data.get("title", "")
            body = pr_data.get("body", "") or ""
            diff = raw.get("diff", "")
            content = f"PR #{pr_number}: {title}\n\n{body}"
            if diff:
                content += f"\n\n--- Diff ---\n{diff[:15000]}"
            chunk = GitHubChunk(
                id=f"github:pr:{repo}:{pr_number}",
                source="github",
                content=content.strip(),
                metadata={
                    "repo": repo,
                    "pr_number": pr_number,
                    "title": title,
                    "updated": pr_data.get("updated_at", ""),
                },
                repo=repo,
                pr_number=pr_number,
                commit_sha=None,
                workflow_run_id=None,
                event_type="pr",
            )
            chunks.append(chunk)

        elif event == "workflow_run" or "workflow_run" in raw:
            wr = raw.get("workflow_run", raw)
            run_id = wr.get("id")
            conclusion = wr.get("conclusion", "")
            logs = raw.get("logs", "")
            content = f"Workflow run {run_id}, conclusion: {conclusion}"
            if logs:
                content += f"\n\nLogs:\n{logs[:12000]}"
            chunk = GitHubChunk(
                id=f"github:workflow:{repo}:{run_id}",
                source="github",
                content=content.strip(),
                metadata={
                    "repo": repo,
                    "workflow_run_id": run_id,
                    "conclusion": conclusion,
                },
                repo=repo,
                pr_number=None,
                commit_sha=wr.get("head_sha"),
                workflow_run_id=run_id,
                event_type="workflow",
            )
            chunks.append(chunk)

        elif event == "push" or "push" in raw:
            commits = raw.get("commits", [])
            for c in commits[:5]:  # Limit to recent commits
                sha = c.get("sha", "")[:8]
                msg = c.get("message", "")
                content = f"Commit {sha}: {msg}"
                chunk = GitHubChunk(
                    id=f"github:commit:{repo}:{sha}",
                    source="github",
                    content=content,
                    metadata={"repo": repo, "commit_sha": sha},
                    repo=repo,
                    pr_number=None,
                    commit_sha=sha,
                    workflow_run_id=None,
                    event_type="commit",
                )
                chunks.append(chunk)

        return chunks

    def to_embedding_payload(self, chunk: GitHubChunk) -> str:
        """Format for embedding."""
        return chunk.content
