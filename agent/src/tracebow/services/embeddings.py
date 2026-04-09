"""Embedding service for vector RAG using local Ollama."""
from __future__ import annotations

import logging
from typing import Any

from tracebow.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generate embeddings via local Ollama nomic-embed or similar."""

    def __init__(self) -> None:
        self._client: Any = None
        self._model = get_settings().embedding_model

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from langchain_ollama import ChatOllama
                from langchain_ollama.embeddings import OllamaEmbeddings

                self._embeddings = OllamaEmbeddings(
                    model=self._model,
                    base_url=get_settings().ollama_base_url,
                )
                logger.info("Embedding service initialized with model %s", self._model)
            except ImportError:
                logger.warning(
                    "langchain-ollama not installed; using mock embeddings. "
                    "Install with: pip install langchain-ollama"
                )
                self._embeddings = _MockEmbeddings()

        return self._embeddings

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string."""
        client = self._get_client()
        return client.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple text strings."""
        client = self._get_client()
        return client.embed_documents(texts)


class _MockEmbeddings:
    """Fallback when Ollama embeddings are unavailable."""

    def embed_query(self, text: str) -> list[float]:
        # Deterministic placeholder for testing
        return [0.1] * 768

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]
