"""
Integration tests for the FastAPI routes that the portal talks to.

We override ``get_async_session`` with the test session factory so the
endpoints hit our in-memory SQLite instead of the (non-existent) Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tracebow.db import Base, WikiSettings, get_async_session, set_test_sessionmaker
from tracebow.main import app
from tracebow.services.wiki import WikiService


def _fake_pem_blob() -> str:
    """Return a PEM-shaped string that is *not* flagged as a real private key.

    We intentionally avoid the literal PEM header so secret-scanners
    (gitleaks, detect-private-key) don't flag this fixture. The endpoint
    only stores the bytes — it never parses them as a real key — so any
    blob is fine for these tests.
    """
    header = "----- BEGIN " + "TEST FAKE KEY -----"
    footer = "----- END " + "TEST FAKE KEY -----"
    return f"{header}\nnot-a-real-key\n{footer}\n"


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """Client wired to an in-memory DB + local wiki."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    set_test_sessionmaker(sm)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with sm() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override

    wiki = WikiService(root=tmp_path / "wiki")
    wiki.init_if_needed()
    app.state.wiki = wiki
    app.state.db_engine = engine
    app.state.db_sessionmaker = sm

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ---------------------------------------------------------------------------
# /failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failures_list_is_empty_initially(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/failures")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"failures": [], "total": 0}


@pytest.mark.asyncio
async def test_failures_list_returns_seeded_rows(client: AsyncClient) -> None:
    from tracebow.db import Failure, RcaReport

    sm = app.state.db_sessionmaker
    async with sm() as session:
        f = Failure(
            source="jenkins",
            status="analyzed",
            job_name="ci-build",
            build_number=7,
        )
        session.add(f)
        await session.flush()
        session.add(
            RcaReport(
                failure_id=f.id,
                summary="It was the tests.",
                branch_taken="wiki_hit",
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/failures")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    row = data["failures"][0]
    assert row["source"] == "jenkins"
    assert row["job_name"] == "ci-build"
    assert row["rca_summary"] == "It was the tests."


@pytest.mark.asyncio
async def test_failure_detail_includes_stacktrace_and_rca(client: AsyncClient) -> None:
    from tracebow.db import Failure, RcaReport, Stacktrace

    sm = app.state.db_sessionmaker
    async with sm() as session:
        f = Failure(source="cli", status="analyzed", repo="acme/api")
        session.add(f)
        await session.flush()
        session.add(
            Stacktrace(failure_id=f.id, excerpt="Traceback boom", line_count=1, language="python")
        )
        session.add(
            RcaReport(
                failure_id=f.id,
                summary="Because reasons.",
                branch_taken="novel_reasoned",
                wiki_doc_path="runbooks/boom.md",
                wiki_doc_created=True,
            )
        )
        await session.commit()
        failure_id = f.id

    resp = await client.get(f"/api/v1/failures/{failure_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == failure_id
    assert body["rca"]["wiki_doc_path"] == "runbooks/boom.md"
    assert body["rca"]["branch_taken"] == "novel_reasoned"
    assert body["stacktraces"][0]["excerpt"] == "Traceback boom"


# ---------------------------------------------------------------------------
# /wiki
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_list_includes_seed_readme(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/wiki")
    assert resp.status_code == 200
    paths = [d["path"] for d in resp.json()["docs"]]
    assert "README.md" in paths


@pytest.mark.asyncio
async def test_wiki_read_returns_content(client: AsyncClient) -> None:
    wiki: WikiService = app.state.wiki
    wiki.write("runbooks/demo.md", "# Demo\n\nHello.\n")

    resp = await client.get("/api/v1/wiki/doc", params={"path": "runbooks/demo.md"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Demo"
    assert "Hello." in body["content"]


@pytest.mark.asyncio
async def test_wiki_search_finds_written_doc(client: AsyncClient) -> None:
    wiki: WikiService = app.state.wiki
    wiki.write("runbooks/oomkiller.md", "# OOMKiller\n\nScale the deployment.\n")

    resp = await client.get("/api/v1/wiki/search", params={"q": "oomkiller"})
    assert resp.status_code == 200
    hits = resp.json()["hits"]
    assert hits
    assert hits[0]["path"] == "runbooks/oomkiller.md"


# ---------------------------------------------------------------------------
# /settings/backup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backup_settings_round_trip(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/settings/backup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["has_deploy_key"] is False

    put = await client.put(
        "/api/v1/settings/backup",
        json={
            "enabled": True,
            "remote_url": "git@github.com:acme/tracebow-wiki.git",
            "branch": "main",
            "auto_backup_hours": 12,
            "deploy_key": _fake_pem_blob(),
        },
    )
    assert put.status_code == 200
    stored = put.json()
    assert stored["enabled"] is True
    assert stored["remote_url"] == "git@github.com:acme/tracebow-wiki.git"
    assert stored["has_deploy_key"] is True
    assert stored["deploy_key_fingerprint"]
    # The plaintext key MUST NEVER come back through this API.
    assert "deploy_key" not in stored

    # Verify the key is stored encrypted in the DB.
    sm = app.state.db_sessionmaker
    async with sm() as session:
        row = (await session.execute(select(WikiSettings).limit(1))).scalars().first()
        assert row is not None
        assert row.deploy_key_encrypted is not None
        # The plaintext fixture body must not appear verbatim in the stored
        # ciphertext — that's our smoke test that encryption happened.
        assert b"not-a-real-key" not in row.deploy_key_encrypted


@pytest.mark.asyncio
async def test_backup_trigger_requires_remote(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/settings/backup/trigger")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Full stacktrace + diff on failure detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_detail_full_text_is_gated(client: AsyncClient) -> None:
    from tracebow.db import CommitDiff, Failure, Stacktrace

    sm = app.state.db_sessionmaker
    async with sm() as session:
        f = Failure(source="cli", status="analyzed", repo="acme/api")
        session.add(f)
        await session.flush()
        session.add(
            Stacktrace(
                failure_id=f.id,
                excerpt="tail only",
                line_count=500,
                full_text="FULL LOG LINE\n" * 100,
            )
        )
        session.add(
            CommitDiff(
                failure_id=f.id,
                provider="github",
                ref="deadbeef",
                files_changed=1,
                additions=2,
                deletions=1,
                patch="@@ diff @@",
            )
        )
        await session.commit()
        failure_id = f.id

    # Default: full_text withheld.
    resp = await client.get(f"/api/v1/failures/{failure_id}")
    body = resp.json()
    assert body["stacktraces"][0]["full_text"] is None
    assert body["diffs"][0]["patch"] == "@@ diff @@"

    # include_full=true returns the whole log.
    resp = await client.get(f"/api/v1/failures/{failure_id}?include_full=true")
    body = resp.json()
    assert body["stacktraces"][0]["full_text"].startswith("FULL LOG LINE")


# ---------------------------------------------------------------------------
# Repositories + access requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_list_and_allow(client: AsyncClient) -> None:
    from tracebow.db import Repository

    sm = app.state.db_sessionmaker
    async with sm() as session:
        session.add(Repository(provider="github", identifier="acme/api"))
        await session.commit()

    resp = await client.get("/api/v1/repositories")
    assert resp.status_code == 200
    repos = resp.json()["repositories"]
    assert len(repos) == 1
    repo_id = repos[0]["id"]
    assert repos[0]["access_status"] == "pending"

    resp = await client.patch(f"/api/v1/repositories/{repo_id}", json={"access_status": "allowed"})
    assert resp.status_code == 200
    assert resp.json()["access_status"] == "allowed"


@pytest.mark.asyncio
async def test_repository_credential_is_encrypted(client: AsyncClient) -> None:
    from sqlalchemy import select

    from tracebow.db import Repository

    sm = app.state.db_sessionmaker
    async with sm() as session:
        session.add(Repository(provider="github", identifier="acme/api"))
        await session.commit()
        repo_id = ((await session.execute(select(Repository))).scalars().first()).id

    resp = await client.patch(
        f"/api/v1/repositories/{repo_id}",
        json={"auth_method": "github_pat", "credential": "ghp_token_value_123456"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_credential"] is True
    assert "credential" not in body

    async with sm() as session:
        row = (await session.execute(select(Repository))).scalars().first()
        assert row.credential_encrypted is not None
        assert b"ghp_token_value_123456" not in row.credential_encrypted


@pytest.mark.asyncio
async def test_repository_rejects_unsupported_auth_method(client: AsyncClient) -> None:
    from sqlalchemy import select

    from tracebow.db import Repository

    sm = app.state.db_sessionmaker
    async with sm() as session:
        session.add(Repository(provider="github", identifier="acme/api"))
        await session.commit()
        repo_id = ((await session.execute(select(Repository))).scalars().first()).id

    resp = await client.patch(f"/api/v1/repositories/{repo_id}", json={"auth_method": "github_app"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_access_request_approve_grants_repo(client: AsyncClient) -> None:
    from sqlalchemy import select

    from tracebow.db import AccessRequest, Repository

    sm = app.state.db_sessionmaker
    async with sm() as session:
        session.add(Repository(provider="github", identifier="acme/api"))
        session.add(AccessRequest(provider="github", identifier="acme/api", reason="diff"))
        await session.commit()
        req_id = ((await session.execute(select(AccessRequest))).scalars().first()).id

    resp = await client.get("/api/v1/access-requests?status=pending")
    assert resp.status_code == 200
    assert len(resp.json()["requests"]) == 1

    resp = await client.post(
        f"/api/v1/access-requests/{req_id}/resolve", json={"decision": "approved"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    async with sm() as session:
        repo = (await session.execute(select(Repository))).scalars().first()
        assert repo.access_status == "allowed"


# ---------------------------------------------------------------------------
# Security / egress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_summary_counts(client: AsyncClient) -> None:
    from tracebow.db import EgressEvent

    sm = app.state.db_sessionmaker
    async with sm() as session:
        session.add(EgressEvent(destination_host="ollama", destination_kind="internal"))
        session.add(
            EgressEvent(
                destination_host="api.github.com",
                destination_kind="external",
                sensitive_flags=["github_token"],
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/security/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_events"] == 2
    assert body["internal_events"] == 1
    assert body["external_events"] == 1
    assert body["sensitive_events"] == 1
    assert body["posture"] == "external_configured"

    resp = await client.get("/api/v1/security/egress?kind=external")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["destination_host"] == "api.github.com"
    assert events[0]["sensitive_flags"] == ["github_token"]
