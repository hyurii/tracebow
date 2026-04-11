"""
Regression: CLI RCA must populate context, retrieval query, and deep RCA model.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tracebow.agent import RCAAgent


def test_build_context_cli_extracts_repo_job_query() -> None:
    agent = RCAAgent(retrieval=MagicMock(), graph=MagicMock())
    payload = {
        "repository": "org/repo",
        "job_name": "ci-build",
        "query": "Analyze build failure for org/repo job ci-build",
        "log_content": "ERROR failed",
        "pr_number": "42",
    }
    ctx = agent._build_context("cli", payload)
    assert ctx["event_type"] == "cli"
    assert ctx["repo"] == "org/repo"
    assert ctx["job_name"] == "ci-build"
    assert "Analyze build failure" in ctx["query"]
    assert ctx["pr_number"] == "42"


@pytest.mark.asyncio
async def test_retrieve_context_cli_includes_query_in_hybrid_search() -> None:
    """Base query from job/repo must still append the CLI `query` string."""
    retrieval = MagicMock()
    retrieval.hybrid_search = AsyncMock(return_value=[])
    graph = MagicMock()
    graph.get_blast_radius = AsyncMock(return_value={"affected": []})

    agent = RCAAgent(retrieval=retrieval, graph=graph)
    context = {
        "event_type": "cli",
        "repo": "org/repo",
        "job_name": "ci-build",
        "query": "Analyze build failure for org/repo job ci-build",
    }
    await agent._retrieve_context(context)

    retrieval.hybrid_search.assert_awaited_once()
    call_query = retrieval.hybrid_search.call_args[0][0]
    assert "Jenkins job ci-build" in call_query
    assert "repository org/repo" in call_query
    assert "Analyze build failure" in call_query


@pytest.mark.asyncio
async def test_analyze_cli_uses_rca_model() -> None:
    agent = RCAAgent(retrieval=MagicMock(), graph=MagicMock())
    agent._build_context = MagicMock(
        return_value={
            "event_type": "cli",
            "repo": "x",
            "job_name": "j",
            "query": "q",
        }
    )
    agent._retrieve_context = AsyncMock(return_value={"chunks": [], "graph_nodes": []})
    agent._synthesize_rca = AsyncMock(return_value={"status": "completed"})

    fake_settings = MagicMock()
    fake_settings.ollama_model = "fast-model"
    fake_settings.ollama_model_rca = "deep-rca-model"

    payload = {"repository": "o/r", "job_name": "j", "query": "q"}
    with patch("tracebow.agent.get_settings", return_value=fake_settings):
        await agent.analyze("cli", payload)

    agent._synthesize_rca.assert_awaited_once()
    used_model = agent._synthesize_rca.call_args.kwargs.get("llm_model")
    assert used_model == "deep-rca-model"
