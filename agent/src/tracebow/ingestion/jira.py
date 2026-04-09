"""Jira issue ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tracebow.ingestion.base import IngestionPipeline, RawDocument

if TYPE_CHECKING:
    from tracebow.services.embeddings import EmbeddingService


@dataclass
class JiraIssueChunk(RawDocument):
    """Jira issue chunk for RCA knowledge base."""

    issue_key: str
    issue_type: str
    resolution: str | None
    resolution_comment: str | None


class JiraIngestionPipeline(IngestionPipeline[JiraIssueChunk]):
    """Ingests Jira issues via REST API, incremental sync."""

    def parse(self, raw: dict) -> list[JiraIssueChunk]:
        """Parse Jira API response into chunks."""
        fields = raw.get("fields", raw)
        summary = fields.get("summary", "")
        description = fields.get("description", "") or ""
        issue_key = raw.get("key", "UNKNOWN")
        issue_type = (fields.get("issuetype") or {}).get("name", "Task")
        resolution = (fields.get("resolution") or {}).get("name")
        comment_obj = fields.get("comment", {})
        comments = comment_obj.get("comments", [])
        resolution_comment = ""
        for c in reversed(comments):
            body = (c.get("body") or {}).get("content", [])
            if isinstance(body, list):
                text_parts = []
                for blk in body:
                    if blk.get("type") == "paragraph":
                        for p in blk.get("content", []):
                            if p.get("type") == "text":
                                text_parts.append(p.get("text", ""))
                resolution_comment = " ".join(text_parts)
            elif isinstance(body, str):
                resolution_comment = body
            if resolution_comment:
                break

        content_parts = [f"Summary: {summary}", f"Description: {description}"]
        if resolution_comment:
            content_parts.append(f"Resolution: {resolution_comment}")
        content = "\n\n".join(content_parts).strip()

        if not content:
            return []

        chunk = JiraIssueChunk(
            id=f"jira:{issue_key}",
            source="jira",
            content=content,
            metadata={
                "issue_key": issue_key,
                "issue_type": issue_type,
                "resolution": resolution,
                "updated": raw.get("fields", {}).get("updated", raw.get("updated", "")),
            },
            issue_key=issue_key,
            issue_type=issue_type,
            resolution=resolution,
            resolution_comment=resolution_comment if resolution_comment else None,
        )
        return [chunk]

    def to_embedding_payload(self, chunk: JiraIssueChunk) -> str:
        """Format for embedding."""
        return chunk.content
