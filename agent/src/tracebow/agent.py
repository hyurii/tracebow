"""Agentic orchestration engine implementing Context-Planning-Action (C-P-A) loop."""

from __future__ import annotations

import logging
from typing import Any

from tracebow.config import get_settings
from tracebow.services.graph import GraphService
from tracebow.services.retrieval import RetrievalService

logger = logging.getLogger(__name__)


class RCAAgent:
    """
    Autonomous agent for root cause analysis.
    Operates on C-P-A: Context (ingest, retrieve), Planning (hypothesis), Action (synthesize).
    """

    def __init__(
        self,
        retrieval: RetrievalService | None = None,
        graph: GraphService | None = None,
    ) -> None:
        self.retrieval = retrieval or RetrievalService()
        self.graph = graph or GraphService()

    async def analyze(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Run the agentic RCA loop for a pipeline failure event.
        """
        context = self._build_context(event_type, payload)
        logger.info("RCA context assembled for %s", event_type)

        # Retrieve relevant artifacts via hybrid RAG + graph
        retrieved = await self._retrieve_context(context)
        logger.info(
            "Retrieved %d chunks, %d graph nodes",
            len(retrieved.get("chunks", [])),
            len(retrieved.get("graph_nodes", [])),
        )

        settings = get_settings()
        llm_model = (
            settings.ollama_model_rca
            if event_type in ("jenkins", "github")
            else settings.ollama_model
        )
        # Plan and synthesize RCA (in production: delegate to local LLM)
        rca = await self._synthesize_rca(context, retrieved, llm_model=llm_model)
        return rca

    def _build_context(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Build initial context from webhook payload."""
        ctx: dict[str, Any] = {"event_type": event_type, "payload": payload}

        if event_type == "jenkins":
            ctx["job_name"] = payload.get("job_name")
            ctx["build_number"] = payload.get("build_number")
            ctx["commit"] = payload.get("git_commit")
            ctx["console_url"] = payload.get("console_url")

        elif event_type == "github":
            repo = payload.get("repository")
            ctx["repo"] = (
                repo
                if isinstance(repo, str)
                else (repo.get("full_name") if isinstance(repo, dict) else None)
            )
            ctx["run_id"] = payload.get("run_id")
            ctx["workflow"] = payload.get("workflow_name") or payload.get("workflow")
            ctx["commit"] = payload.get("head_sha")
            ctx["pr_number"] = payload.get("pull_request_number") or (
                payload.get("pull_request", {}).get("number")
                if isinstance(payload.get("pull_request"), dict)
                else None
            )

        elif event_type in ("chat", "generic"):
            ctx["query"] = payload.get("query", "")

        return ctx

    async def _retrieve_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Hybrid retrieval: vector + BM25 + graph traversal."""
        query_parts = []
        if context.get("job_name"):
            query_parts.append(f"Jenkins job {context['job_name']}")
        if context.get("commit"):
            query_parts.append(f"commit {context['commit'][:8]}")
        if context.get("repo"):
            query_parts.append(f"repository {context['repo']}")

        query = (
            " ".join(query_parts)
            if query_parts
            else context.get("query", "pipeline failure build log")
        )

        chunks = await self.retrieval.hybrid_search(query, top_k=10)
        graph_nodes: list[dict] = []

        if context.get("repo") or context.get("commit"):
            try:
                result = await self.graph.get_blast_radius(
                    repo=context.get("repo") or "",
                    commit_sha=context.get("commit", "")[:8],
                )
                affected = result.get("affected", []) if isinstance(result, dict) else []
                graph_nodes = [
                    {"id": f"{r.get('type', '')}:{r.get('name', '')}:{r.get('repo', '')}", **r}
                    for r in affected
                ]
            except Exception as e:
                logger.warning("Graph blast radius lookup failed: %s", e)
                graph_nodes = []

        return {"chunks": chunks, "graph_nodes": graph_nodes}

    async def _synthesize_rca(
        self,
        context: dict[str, Any],
        retrieved: dict[str, Any],
        llm_model: str,
    ) -> dict[str, Any]:
        """Synthesize final RCA report (placeholder; in production, call local LLM)."""
        chunks = retrieved.get("chunks", [])
        graph_nodes = retrieved.get("graph_nodes", [])

        # In production: ChatOllama(model=llm_model, base_url=...) with this prompt
        logger.info("RCA synthesis will use Ollama model %s", llm_model)
        # For now: structured placeholder
        summary = (
            f"RCA triggered for {context.get('event_type', 'unknown')} event "
            f"(model={llm_model}). "
            f"Retrieved {len(chunks)} relevant chunks and {len(graph_nodes)} related graph nodes."
        )

        return {
            "status": "completed",
            "event_type": context.get("event_type"),
            "summary": summary,
            "retrieved_chunk_count": len(chunks),
            "blast_radius_components": [n.get("id") for n in graph_nodes[:10]],
            "recommendations": [
                "Review retrieved log chunks for error signatures.",
                "Check blast radius for upstream/downstream impacts.",
            ],
        }


async def run_rca_agent(query: str, context: dict[str, Any] | None = None) -> str:
    """
    Entry point for chat and on-demand RCA.
    Runs the agent and returns a human-readable summary string.
    """
    agent = RCAAgent()
    ctx = context or {}
    source = ctx.get("source")
    if source == "jenkins":
        payload = {
            "job_name": ctx.get("job_or_repo"),
            "build_number": ctx.get("build_or_run_id"),
            "git_commit": ctx.get("git_commit"),
            **{
                k: v
                for k, v in ctx.items()
                if k not in ("source", "job_or_repo", "build_or_run_id")
            },
        }
        event_type = "jenkins"
    elif source == "github":
        payload = {
            "repository": ctx.get("job_or_repo"),
            "run_id": ctx.get("build_or_run_id"),
            "head_sha": ctx.get("head_sha"),
            "pull_request_number": ctx.get("pr_number"),
            **{
                k: v
                for k, v in ctx.items()
                if k not in ("source", "job_or_repo", "build_or_run_id")
            },
        }
        event_type = "github"
    else:
        payload = {"query": query, **ctx}
        event_type = "chat"
    result = await agent.analyze(event_type, payload)
    return result.get("summary", str(result))
