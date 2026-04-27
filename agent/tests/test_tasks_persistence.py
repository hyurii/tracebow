"""
Tasks layer — verify that an RCA run persists a Failure + RcaReport
(+ Stacktrace when a log is supplied).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tracebow.db import Failure, RcaReport, Stacktrace
from tracebow.tasks import _persist_failure_and_rca


@pytest.mark.asyncio
async def test_persist_failure_and_rca_writes_all_three(db_session, wiki_service) -> None:
    await _persist_failure_and_rca(
        task_id="task-abc",
        event_type="github",
        payload={
            "repository": "acme/api",
            "run_id": 101,
            "workflow_name": "CI",
            "head_sha": "deadbeef",
            "head_branch": "main",
            "run_url": "https://example.invalid/runs/101",
            "log_content": "Traceback\nTypeError: boom\n" + "\n".join(str(i) for i in range(60)),
        },
        rca_result={
            "summary": "It exploded.",
            "branch_taken": "novel_reasoned",
            "wiki_doc_path": "runbooks/boom.md",
            "wiki_doc_created": True,
            "tool_trace": [{"node": "ingest"}],
            "model_used": "stub:deterministic",
            "latency_ms": 42,
        },
    )

    async with db_session.begin():
        await db_session.commit()  # ensure our fixture session doesn't hold a tx

    failures = (await db_session.execute(select(Failure))).scalars().all()
    assert len(failures) == 1
    failure = failures[0]
    assert failure.source == "github"
    assert failure.repo == "acme/api"
    assert failure.run_id == 101
    assert failure.commit_sha == "deadbeef"
    assert failure.task_id == "task-abc"

    stacks = (await db_session.execute(select(Stacktrace))).scalars().all()
    assert len(stacks) == 1
    # We snip to the last 50 lines — should be <= 50.
    assert stacks[0].line_count <= 50
    assert stacks[0].failure_id == failure.id

    reports = (await db_session.execute(select(RcaReport))).scalars().all()
    assert len(reports) == 1
    assert reports[0].summary == "It exploded."
    assert reports[0].branch_taken == "novel_reasoned"
    assert reports[0].wiki_doc_path == "runbooks/boom.md"
    assert reports[0].wiki_doc_created is True
    assert reports[0].model_used == "stub:deterministic"
