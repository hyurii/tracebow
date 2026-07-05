"""LLM factory + tool dispatch for the LangGraph ``reason`` node.

Isolated from :mod:`tracebow.agent` so the reasoning node can build a
tool-bound ``ChatOllama`` and dispatch tool calls without importing the
Ollama client at module import time (tests keep Ollama disabled).

Zero-egress by construction: the only network target is the local Ollama
host plus the already-configured internal integrations behind the tools.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from tracebow.config import get_settings
from tracebow.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

TOOL_REGISTRY: dict[str, BaseTool] = {tool.name: tool for tool in ALL_TOOLS}


def build_reasoning_llm() -> Any:
    """Return a tool-bound ``ChatOllama`` for the RCA reason node.

    Imported lazily so environments without Ollama (and the test suite,
    which forces ``OLLAMA_ENABLED=false``) never pay the import cost.
    """
    from langchain_ollama import ChatOllama

    settings = get_settings()
    llm = ChatOllama(
        model=settings.ollama_model_rca,
        base_url=settings.ollama_base_url,
        temperature=settings.ollama_temperature,
        client_kwargs={"timeout": settings.ollama_request_timeout},
    )
    return llm.bind_tools(ALL_TOOLS)


def invoke_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a single tool call by name, never raising.

    Mirrors the tools' own contract: failures come back as
    ``{"status": "error", ...}`` rather than propagating, so the reasoning
    loop can keep going (or summarize) regardless of tool health.
    """
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return {"status": "error", "error": f"unknown tool: {name}"}
    try:
        result = tool.invoke(args)
    except Exception as exc:  # tools must never crash the graph
        logger.warning("Tool %s raised: %s", name, exc)
        return {"status": "error", "error": str(exc)}
    if isinstance(result, dict):
        return result
    return {"status": "ok", "result": result}
