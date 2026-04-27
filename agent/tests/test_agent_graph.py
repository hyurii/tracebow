"""
LangGraph orchestrator tests.

We only assert the *structural* behaviour of the graph:
- when the wiki has a matching runbook the graph takes the ``wiki_hit`` path,
- when it doesn't the graph calls ``reason`` + writes a new runbook.

The LLM node is a deterministic stub so the tests are fully offline.
"""

from __future__ import annotations

import pytest

from tracebow.agent import RCAAgent


@pytest.mark.asyncio
async def test_graph_wiki_hit_when_runbook_matches(wiki_service) -> None:
    wiki_service.write(
        "runbooks/db-timeout.md",
        "# DB Timeout\n\nKnown fix: restart pgbouncer.\n",
    )

    agent = RCAAgent()
    result = await agent.analyze(
        event_type="cli",
        payload={
            "repository": "acme/api",
            "job_name": "ci-build",
            "log_content": "ERROR database timeout while acquiring connection",
        },
    )

    assert result["branch_taken"] == "wiki_hit"
    assert result["wiki_doc_path"] == "runbooks/db-timeout.md"
    assert "restart pgbouncer" in result["summary"].lower()
    assert result["model_used"].startswith("stub:")


@pytest.mark.asyncio
async def test_graph_novel_path_writes_new_runbook(wiki_service) -> None:
    agent = RCAAgent()
    result = await agent.analyze(
        event_type="jenkins",
        payload={
            "job_name": "nightly-integration",
            "build_number": 42,
            "log_content": "FATAL previously unseen cosmic-ray bitflip in /dev/mem",
        },
    )

    assert result["branch_taken"] == "novel_reasoned"
    assert result["wiki_doc_created"] is True
    assert result["wiki_doc_path"] is not None
    assert result["wiki_doc_path"].startswith("runbooks/")

    written = wiki_service.read(result["wiki_doc_path"])
    assert "Runbook" in written.content
    assert "Stacktrace (tail)" in written.content


@pytest.mark.asyncio
async def test_graph_tool_trace_is_populated(wiki_service) -> None:
    agent = RCAAgent()
    result = await agent.analyze(
        event_type="github",
        payload={"repository": "acme/web", "run_id": 99, "log_content": "Error: boom"},
    )
    assert isinstance(result["tool_trace"], list)
    names = [step["node"] for step in result["tool_trace"]]
    assert names[0] == "ingest"
    assert "search_wiki" in names
