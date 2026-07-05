"""
LangGraph orchestrator tests.

We only assert the *structural* behaviour of the graph:
- when the wiki has a matching runbook the graph takes the ``wiki_hit`` path,
- when it doesn't the graph calls ``reason`` + writes a new runbook.

The LLM node is a deterministic stub so the tests are fully offline.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from tracebow.agent import RCAAgent


def _enable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flip OLLAMA_ENABLED=true for a single test and refresh the cache."""
    from tracebow import config as cfg

    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    cfg.get_settings.cache_clear()  # type: ignore[attr-defined]


class _FakeToolCallingLLM:
    """Minimal stand-in for a tool-bound ChatOllama.

    Returns a canned sequence of AIMessages: first a tool call, then a
    final text answer with no further tool calls.
    """

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.calls: list[Any] = []

    def invoke(self, messages: Any) -> AIMessage:
        self.calls.append(messages)
        return self._responses.pop(0)


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


@pytest.mark.asyncio
async def test_reason_node_runs_tool_calling_loop(
    wiki_service: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_ollama(monkeypatch)

    fake = _FakeToolCallingLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_wiki",
                        "args": {"query": "cosmic ray bitflip"},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="Root cause: transient hardware bitflip. Fix: retry the job.",
            ),
        ]
    )
    monkeypatch.setattr("tracebow.llm.build_reasoning_llm", lambda: fake)

    agent = RCAAgent()
    result = await agent.analyze(
        event_type="jenkins",
        payload={
            "job_name": "nightly-integration",
            "log_content": "FATAL previously unseen cosmic-ray bitflip in /dev/mem",
        },
    )

    assert result["branch_taken"] == "novel_reasoned"
    assert result["model_used"] == "ollama:phi4-mini"

    tool_steps = [s for s in result["tool_trace"] if s.get("tool")]
    assert any(s["tool"] == "search_wiki" for s in tool_steps)

    written = wiki_service.read(result["wiki_doc_path"])
    assert "transient hardware bitflip" in written.content
    # The LLM was invoked twice: tool round + final answer.
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_reason_node_falls_back_to_stub_on_llm_error(
    wiki_service: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_ollama(monkeypatch)

    def _boom() -> Any:
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr("tracebow.llm.build_reasoning_llm", _boom)

    agent = RCAAgent()
    result = await agent.analyze(
        event_type="jenkins",
        payload={
            "job_name": "nightly-integration",
            "log_content": "FATAL previously unseen cosmic-ray bitflip in /dev/mem",
        },
    )

    assert result["branch_taken"] == "novel_reasoned"
    assert result["model_used"].startswith("stub:")
    assert result["wiki_doc_created"] is True
