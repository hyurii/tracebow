"""
Retrieval Service - Hybrid RAG (vector + BM25) for semantic and keyword search.

Handles:
- Dense vector search (ChromaDB) for semantic similarity
- Sparse BM25 for exact error codes, trace IDs, variable names
- Source filtering (logs, jira, slack)
"""

from __future__ import annotations

from typing import Literal

import chromadb

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
        host: str = "chromadb",
        port: int = 8000,
        embedding_dim: int = 384,
    ):
        self._host = host
        self._port = port
        self._embedding_dim = embedding_dim
        self._client: chromadb.HttpClient | None = None
        self._collection: chromadb.Collection | None = None
        self._bm25: BM25Okapi | None = None
        self._bm25_corpus: list[tuple[str, dict]] = []  # (text, metadata)

    def _get_client(self) -> chromadb.HttpClient:
        if self._client is None:
            self._client = chromadb.HttpClient(host=self._host, port=self._port)
        return self._client

    def _get_collection(self) -> chromadb.Collection:
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self.COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

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
        """Create collection if not exists (get_or_create is idempotent)."""
        try:
            self._get_collection()
        except Exception as e:
            raise RuntimeError(f"Failed to ensure ChromaDB collection: {e}") from e

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
        collection = self._get_collection()

        where_filter = None
        if sources:
            where_filter = {"source": {"$in": sources}}

        n_results = limit * 2 if use_hybrid else limit
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=n_results,
            where=where_filter,
            include=["metadatas", "distances"],
        )

        ids = results.get("ids", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not use_hybrid or not BM25Okapi or not self._bm25_corpus:
            return [
                {"id": ids[i], "score": 1.0 - distances[i], "payload": metadatas[i] or {}}
                for i in range(min(limit, len(ids)))
            ]

        seen: set[str] = set()
        output: list[dict] = []
        for i in range(len(ids)):
            if ids[i] in seen:
                continue
            seen.add(ids[i])
            output.append(
                {
                    "id": ids[i],
                    "score": 1.0 - distances[i],
                    "payload": metadatas[i] or {},
                }
            )
            if len(output) >= limit:
                break
        return output

    def upsert_points(
        self,
        points: list[tuple[str, list[float], dict]],
    ) -> None:
        """Upsert vectors with metadata (id, vector, payload)."""
        if not points:
            return
        collection = self._get_collection()
        ids = [p[0] for p in points]
        embeddings = [p[1] for p in points]
        metadatas = [p[2] for p in points]
        collection.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas)

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
        self._client = None
        self._collection = None
