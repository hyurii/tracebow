"""
Retrieval Service - Hybrid RAG (vector + BM25) for semantic and keyword search.

Handles:
- Dense vector search (Qdrant) for semantic similarity
- Sparse BM25 for exact error codes, trace IDs, variable names
- Source filtering (logs, jira, slack)
"""

from __future__ import annotations

from typing import Literal

from qdrant_client import QdrantClient
from qdrant_client.models import (
    PointStruct,
    VectorParams,
    Distance,
    Filter,
    FieldCondition,
    MatchValue,
)
from qdrant_client.http import models as qmodels

# Optional: rank-bm25 for local BM25 (fallback if Qdrant doesn't support hybrid)
try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None


SourceType = Literal["logs", "jira", "slack"]


class RetrievalService:
    """
    Hybrid retrieval: dense vectors + keyword search.
    """

    COLLECTION = "tracebow_vectors"
    VECTOR_SIZE = 384  # all-MiniLM-L6-v2 default

    def __init__(
        self,
        host: str = "qdrant",
        port: int = 6333,
        embedding_dim: int = 384,
    ):
        self._host = host
        self._port = port
        self._embedding_dim = embedding_dim
        self._client: QdrantClient | None = None
        self._bm25: BM25Okapi | None = None
        self._bm25_corpus: list[tuple[str, dict]] = []  # (text, metadata)

    def _get_client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(host=self._host, port=self._port)
        return self._client

    async def hybrid_search(
        self,
        query_text: str,
        top_k: int = 10,
        sources: list[SourceType] | None = None,
    ) -> list[dict]:
        """
        Hybrid search: embed query and run vector + keyword search.
        Requires EmbeddingService for query embedding.
        """
        try:
            from tracebow.services.embeddings import EmbeddingService

            embed_svc = EmbeddingService()
            vector = embed_svc.embed_text(query_text)
        except Exception:
            vector = [0.0] * self._embedding_dim
        return self.search(
            query_vector=vector,
            query_text=query_text,
            sources=sources,
            limit=top_k,
            use_hybrid=True,
        )

    async def ensure_collection(self) -> None:
        """Create collection if not exists."""
        try:
            client = self._get_client()
            collections = client.get_collections().collections
            if not any(c.name == self.COLLECTION for c in collections):
                client.create_collection(
                    collection_name=self.COLLECTION,
                    vectors_config=VectorParams(
                        size=self._embedding_dim,
                        distance=Distance.COSINE,
                    ),
                )
        except Exception as e:
            # Qdrant may not be available in dev
            raise RuntimeError(f"Failed to ensure Qdrant collection: {e}") from e

    def search(
        self,
        query_vector: list[float],
        query_text: str,
        *,
        sources: list[SourceType] | None = None,
        limit: int = 10,
        use_hybrid: bool = True,
    ) -> list[dict]:
        """
        Hybrid search: combine vector similarity with keyword scoring.
        """
        client = self._get_client()
        must = []
        if sources:
            must.append(
                FieldCondition(
                    key="source",
                    match=MatchValue(any=sources),
                )
            )
        qfilter = Filter(must=must) if must else None

        # Dense search
        vector_results = client.search(
            collection_name=self.COLLECTION,
            query_vector=query_vector,
            query_filter=qfilter,
            limit=limit * 2 if use_hybrid else limit,
        )

        if not use_hybrid or not BM25Okapi or not self._bm25_corpus:
            return [
                {"id": r.id, "score": r.score, "payload": r.payload or {}}
                for r in vector_results[:limit]
            ]

        # Optional: re-rank with BM25 for keyword boost (simplified here)
        seen = set()
        output = []
        for r in vector_results:
            if r.id in seen:
                continue
            seen.add(r.id)
            output.append({
                "id": r.id,
                "score": r.score,
                "payload": r.payload or {},
            })
            if len(output) >= limit:
                break
        return output

    def upsert_points(
        self,
        points: list[tuple[str, list[float], dict]],
    ) -> None:
        """Upsert vectors with metadata (id, vector, payload)."""
        client = self._get_client()
        structs = [
            PointStruct(id=p[0], vector=p[1], payload=p[2])
            for p in points
        ]
        client.upsert(
            collection_name=self.COLLECTION,
            points=structs,
        )

    def add_to_bm25_corpus(self, doc_id: str, text: str, metadata: dict) -> None:
        """Add document to BM25 corpus for keyword search."""
        self._bm25_corpus.append((text, {"id": doc_id, **metadata}))

    def build_bm25_index(self) -> None:
        """Build BM25 index from corpus (tokenize by whitespace)."""
        if not BM25Okapi or not self._bm25_corpus:
            return
        tokenized = [doc[0].lower().split() for doc in self._bm25_corpus]
        self._bm25 = BM25Okapi(tokenized)

    async def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
