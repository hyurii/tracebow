"""Slack channel and thread ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tracebow.ingestion.base import IngestionPipeline, RawDocument

if TYPE_CHECKING:
    from tracebow.services.embeddings import EmbeddingService


@dataclass
class SlackThreadChunk(RawDocument):
    """Slack thread or message bundle for semantic search."""

    channel_id: str
    channel_name: str | None
    thread_ts: str | None
    user_name: str | None


class SlackIngestionPipeline(IngestionPipeline[SlackThreadChunk]):
    """Ingests Slack channels, preserving thread hierarchy."""

    def parse(self, raw: dict) -> list[SlackThreadChunk]:
        """Parse Slack API messages/threads into cohesive chunks."""
        channel_id = raw.get("channel_id", raw.get("channel", ""))
        channel_name = raw.get("channel_name", "")
        messages = raw.get("messages", [raw])
        if not isinstance(messages, list):
            messages = [messages]

        # Group by thread_ts; root messages have thread_ts == ts or missing
        threads: dict[str, list[dict]] = {}
        for msg in messages:
            ts = msg.get("ts", "")
            thread_ts = msg.get("thread_ts") or msg.get("ts")
            if thread_ts not in threads:
                threads[thread_ts] = []
            threads[thread_ts].append(msg)

        chunks: list[SlackThreadChunk] = []
        for thread_ts, msgs in threads.items():
            content_parts: list[str] = []
            user_names: list[str] = []
            for m in sorted(msgs, key=lambda x: x.get("ts", "")):
                user = m.get("user", "")
                user_names.append(user)
                text = self._extract_text(m)
                if text:
                    content_parts.append(text)
            content = "\n".join(content_parts).strip()
            if not content or self._is_off_topic(content):
                continue
            chunk = SlackThreadChunk(
                id=f"slack:{channel_id}:{thread_ts}",
                source="slack",
                content=content,
                metadata={
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "thread_ts": thread_ts,
                    "message_count": len(msgs),
                },
                channel_id=channel_id,
                channel_name=channel_name,
                thread_ts=thread_ts,
                user_name=user_names[0] if user_names else None,
            )
            chunks.append(chunk)
        return chunks

    def _extract_text(self, msg: dict) -> str:
        """Extract plain text from Slack message blocks."""
        text = msg.get("text", "")
        if text:
            return text
        blocks = msg.get("blocks", [])
        parts = []
        for b in blocks:
            if b.get("type") == "section":
                sec = b.get("text", {})
                if isinstance(sec, dict):
                    parts.append(sec.get("text", ""))
                else:
                    parts.append(str(sec))
        return " ".join(parts).strip()

    def _is_off_topic(self, content: str) -> bool:
        """Heuristic to skip clearly non-technical threads."""
        low = content.lower()
        if len(content) < 30:
            return True
        # Emoji-heavy, greetings only
        if content.count(":") > len(content) / 10:
            return True
        return False

    def to_embedding_payload(self, chunk: SlackThreadChunk) -> str:
        """Format for embedding."""
        prefix = f"[Slack #{chunk.channel_name or chunk.channel_id}]"
        return f"{prefix}\n{chunk.content}"
