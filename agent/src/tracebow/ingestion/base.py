"""Base ingester with common chunking and indexing logic."""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from typing import Any

from tracebow.services.embeddings import EmbeddingService
from tracebow.services.retrieval import RetrievalService
from tracebow.services.graph import GraphService

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """Simple sliding-window chunking with overlap."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = end - overlap
    return chunks


def _content_id(source: str, key: str) -> str:
    return hashlib.sha256(f"{source}:{key}".encode()).hexdigest()[:16]


class BaseIngester(ABC):
    """Abstract base for all data ingestors."""

    def __init__(
        self,
        retrieval: RetrievalService | None = None,
        graph: GraphService | None = None,
        embeddings: EmbeddingService | None = None,
    ) -> None:
        self.retrieval = retrieval or RetrievalService()
        self.graph = graph or GraphService()
        self.embeddings = embeddings or EmbeddingService()

    @abstractmethod
    async def sync(self) -> dict[str, Any]:
        """Perform incremental sync; return stats."""

    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this data source."""
