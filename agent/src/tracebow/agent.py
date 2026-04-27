"""
LangGraph-based SRE orchestrator.

Graph shape::

    ingest ─► search_wiki ─► (wiki_hit?)
                               ├── yes ─► read_wiki ─► finalize (branch=wiki_hit)
                               └── no  ─► reason ─► write_wiki ─► finalize (branch=novel_reasoned)

The ``reason`` node is a DETERMINISTIC STUB by design — we wanted the
full LangGraph wiring, the native tools, the wiki I/O, the DB, and the
API to land first. When ``OLLAMA_ENABLED=true`` and Ollama is reachable,
a follow-up change will swap the stub for a real ``ChatOllama`` call
that binds :mod:`tracebow.tools.ALL_TOOLS`. The graph shape does not
need to change for that swap.

State is a plain ``TypedDict`` so it can round-trip through Celery's
JSON serializer — we never put live Python objects in there.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from tracebow.config import get_settings
from tracebow.services.wiki import WikiError, WikiService

logger = logging.getLogger(__name__)

MAX_STACKTRACE_LINES = 50
TOP_K_WIKI = 5
WIKI_HIT_THRESHOLD = 2.0


class GraphState(TypedDict, total=False):
    event_type: str
    payload: dict[str, Any]
    query: str
    stacktrace: str
    wiki_hits: list[dict[str, Any]]
    wiki_doc: dict[str, Any] | None
    branch_taken: str
    summary: str
    wiki_doc_created: bool
    wiki_doc_path: str | None
    model_used: str
    tool_trace: list[dict[str, Any]]
    latency_ms: int
    started_at: float


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _node_ingest(state: GraphState) -> GraphState:
    payload = state.get("payload", {}) or {}
    event_type = state.get("event_type", "unknown")
    stacktrace = _snip_stacktrace(payload)
    query = _build_query(event_type, payload, stacktrace)

    return {
        **state,
        "query": query,
        "stacktrace": stacktrace,
        "tool_trace": [{"node": "ingest", "event_type": event_type}],
        "started_at": time.monotonic(),
    }


def _node_search_wiki(state: GraphState) -> GraphState:
    query = state.get("query", "")
    try:
        hits = WikiService().search(query, limit=TOP_K_WIKI)
    except WikiError as exc:
        logger.warning("Wiki search failed: %s", exc)
        hits = []

    serialized = [
        {"path": h.path, "title": h.title, "excerpt": h.excerpt, "score": h.score} for h in hits
    ]
    trace = list(state.get("tool_trace", []))
    trace.append({"node": "search_wiki", "hit_count": len(serialized)})
    return {**state, "wiki_hits": serialized, "tool_trace": trace}


def _node_read_wiki(state: GraphState) -> GraphState:
    hits = state.get("wiki_hits") or []
    if not hits:
        return {**state, "wiki_doc": None}

    top = hits[0]
    try:
        doc = WikiService().read(top["path"])
    except WikiError as exc:
        logger.warning("Wiki read failed for %s: %s", top.get("path"), exc)
        return {**state, "wiki_doc": None}

    trace = list(state.get("tool_trace", []))
    trace.append({"node": "read_wiki", "path": doc.path})
    return {
        **state,
        "wiki_doc": {"path": doc.path, "title": doc.title, "content": doc.content},
        "tool_trace": trace,
    }


def _node_reason(state: GraphState) -> GraphState:
    """Deterministic stub for now — see module docstring.

    Emits a templated recommendation using whatever structured context
    we already have. Honest about being a stub so the UI shows the
    right caveat and we don't pretend we called an LLM.
    """
    settings = get_settings()
    event_type = state.get("event_type", "unknown")
    stacktrace = state.get("stacktrace", "")
    payload = state.get("payload", {}) or {}

    header_lines = [
        f"Tracebow novel-error triage for {event_type} event.",
        "No matching runbook found in the wiki — generating a first-pass template.",
    ]
    if payload.get("repo") or payload.get("repository"):
        header_lines.append(f"Repository: {payload.get('repo') or payload.get('repository')}")
    if payload.get("job_name"):
        header_lines.append(f"Job: {payload['job_name']}")
    commit = payload.get("commit_sha") or payload.get("git_commit") or payload.get("head_sha")
    if commit:
        header_lines.append(f"Commit: {commit}")

    hint = _first_failure_line(stacktrace)
    if hint:
        header_lines.append(f"First failure signal: {hint}")

    body = "\n".join(
        [
            *header_lines,
            "",
            "Likely next steps:",
            "- Inspect the failing step's last 50 lines of output (captured below).",
            "- Compare recent commits / PR diffs using the `get_github_pr_files` tool.",
            "- Query Jira for open incidents referencing the same signature.",
            "- If a fix is confirmed, update the generated runbook in the wiki.",
        ]
    )

    mode = "stub_template" if not settings.ollama_enabled else "stub_template_ollama_skipped"
    trace = list(state.get("tool_trace", []))
    trace.append({"node": "reason", "mode": mode})
    return {
        **state,
        "summary": body,
        "model_used": "stub:deterministic",
        "tool_trace": trace,
    }


def _node_write_wiki(state: GraphState) -> GraphState:
    query = (state.get("query") or "tracebow-unknown").strip()
    slug = _slugify(query) or "novel-failure"
    path = f"runbooks/{slug}.md"

    content = _templated_runbook(
        slug=slug,
        event_type=state.get("event_type", "unknown"),
        summary=state.get("summary", ""),
        stacktrace=state.get("stacktrace", ""),
    )
    trace = list(state.get("tool_trace", []))
    try:
        result = WikiService().write(path, content, message=f"Auto-generate runbook {slug}")
        trace.append(
            {
                "node": "write_wiki",
                "path": result.path,
                "created": result.created,
                "commit": result.commit_sha,
            }
        )
        return {
            **state,
            "wiki_doc_created": bool(result.commit_sha),
            "wiki_doc_path": result.path,
            "tool_trace": trace,
        }
    except WikiError as exc:
        trace.append({"node": "write_wiki", "error": str(exc)})
        logger.warning("Write to wiki failed: %s", exc)
        return {**state, "wiki_doc_created": False, "wiki_doc_path": None, "tool_trace": trace}


def _finalize_wiki_hit(state: GraphState) -> GraphState:
    doc = state.get("wiki_doc")
    summary = (
        f"Known issue resolved from wiki runbook.\n\n"
        f"Source: {doc['path']}\n\n"
        f"Title: {doc['title']}\n\n"
        f"{doc['content']}"
        if doc
        else "Matched the wiki but runbook could not be read — see tool_trace."
    )
    return {
        **state,
        "branch_taken": "wiki_hit",
        "summary": summary,
        "wiki_doc_path": (doc or {}).get("path"),
        "latency_ms": int((time.monotonic() - state.get("started_at", time.monotonic())) * 1000),
    }


def _finalize_novel(state: GraphState) -> GraphState:
    return {
        **state,
        "branch_taken": "novel_reasoned",
        "latency_ms": int((time.monotonic() - state.get("started_at", time.monotonic())) * 1000),
    }


def _should_use_wiki(state: GraphState) -> str:
    hits = state.get("wiki_hits") or []
    if not hits:
        return "novel"
    top = hits[0]
    if float(top.get("score", 0)) >= WIKI_HIT_THRESHOLD:
        return "known"
    return "novel"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------


def build_graph() -> Any:
    graph = StateGraph(GraphState)
    graph.add_node("ingest", _node_ingest)
    graph.add_node("search_wiki", _node_search_wiki)
    graph.add_node("read_wiki", _node_read_wiki)
    graph.add_node("reason", _node_reason)
    graph.add_node("write_wiki", _node_write_wiki)
    graph.add_node("finalize_wiki_hit", _finalize_wiki_hit)
    graph.add_node("finalize_novel", _finalize_novel)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "search_wiki")
    graph.add_conditional_edges(
        "search_wiki",
        _should_use_wiki,
        {"known": "read_wiki", "novel": "reason"},
    )
    graph.add_edge("read_wiki", "finalize_wiki_hit")
    graph.add_edge("reason", "write_wiki")
    graph.add_edge("write_wiki", "finalize_novel")
    graph.add_edge("finalize_wiki_hit", END)
    graph.add_edge("finalize_novel", END)

    return graph.compile()


_COMPILED = None


def _graph() -> Any:
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_graph()
    return _COMPILED


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------


class RCAAgent:
    """Public wrapper preserved for the task layer and tests."""

    async def analyze(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        compiled = _graph()
        initial: GraphState = {"event_type": event_type, "payload": payload or {}}
        result: GraphState = await compiled.ainvoke(initial)
        return _to_public(result)


async def run_rca_agent(query: str, context: dict[str, Any] | None = None) -> str:
    payload = {"query": query, **(context or {})}
    event_type = (context or {}).get("source") or "chat"
    result = await RCAAgent().analyze(event_type, payload)
    return str(result.get("summary", ""))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_public(state: GraphState) -> dict[str, Any]:
    return {
        "status": "completed",
        "event_type": state.get("event_type"),
        "summary": state.get("summary", ""),
        "branch_taken": state.get("branch_taken", "novel_reasoned"),
        "wiki_doc_path": state.get("wiki_doc_path"),
        "wiki_doc_created": bool(state.get("wiki_doc_created", False)),
        "tool_trace": state.get("tool_trace", []),
        "model_used": state.get("model_used", "stub:deterministic"),
        "latency_ms": state.get("latency_ms"),
    }


def _snip_stacktrace(payload: dict[str, Any]) -> str:
    raw = (
        payload.get("log_content")
        or payload.get("console_output")
        or payload.get("log")
        or payload.get("stacktrace")
        or ""
    )
    if not isinstance(raw, str) or not raw:
        return ""
    lines = raw.splitlines()
    if len(lines) <= MAX_STACKTRACE_LINES:
        return "\n".join(lines)
    return "\n".join(lines[-MAX_STACKTRACE_LINES:])


def _build_query(event_type: str, payload: dict[str, Any], stacktrace: str) -> str:
    parts: list[str] = []
    if payload.get("job_name"):
        parts.append(f"job {payload['job_name']}")
    if payload.get("repository"):
        parts.append(f"repo {payload['repository']}")
    if payload.get("repo"):
        parts.append(f"repo {payload['repo']}")
    if payload.get("workflow_name"):
        parts.append(f"workflow {payload['workflow_name']}")
    if payload.get("query"):
        parts.append(str(payload["query"]))
    first = _first_failure_line(stacktrace)
    if first:
        parts.append(first)
    parts.append(event_type)
    return " ".join(p for p in parts if p).strip()


def _first_failure_line(text: str) -> str:
    if not text:
        return ""
    for line in text.splitlines():
        lower = line.lower()
        if any(kw in lower for kw in ("error", "exception", "failed", "traceback", "fatal")):
            return line.strip()[:200]
    return ""


def _slugify(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_", ".", "/"):
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:80]


def _templated_runbook(slug: str, event_type: str, summary: str, stacktrace: str) -> str:
    header = f"# Runbook: {slug}\n\n"
    meta = (
        f"- **Source event:** `{event_type}`\n"
        f"- **Generated by:** Tracebow agent (stub LLM)\n"
        f"- **Review status:** unreviewed — human editor should verify and refine\n\n"
    )
    body = (
        "## Observation\n\n"
        f"{summary.strip() or 'No summary was produced.'}\n\n"
        "## Stacktrace (tail)\n\n"
        "```\n"
        f"{(stacktrace or '(no stacktrace captured)').strip()}\n"
        "```\n\n"
        "## Proposed fix\n\n"
        "_Pending human review._\n"
    )
    return header + meta + body
