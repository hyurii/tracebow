"""Repository access-control gate tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tracebow.db import AccessRequest, Repository
from tracebow.services import repo_access


def test_derive_source_github_and_jenkins_and_none() -> None:
    assert repo_access.derive_source("github", {"repository": "acme/api"}) == (
        "github",
        "acme/api",
    )
    assert repo_access.derive_source("cli", {"repo": "acme/api"}) == (
        "github",
        "acme/api",
    )
    assert repo_access.derive_source("jenkins", {"job_name": "nightly"}) == (
        "jenkins",
        "nightly",
    )
    assert repo_access.derive_source("jenkins", {}) is None


@pytest.mark.asyncio
async def test_register_is_idempotent_and_defaults_pending(db_session) -> None:
    r1 = await repo_access.register_repository(db_session, "github", "acme/api")
    r2 = await repo_access.register_repository(db_session, "github", "acme/api")
    assert r1.id == r2.id
    assert r1.access_status == repo_access.PENDING

    rows = (await db_session.execute(select(Repository))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_check_access_opens_request_when_not_allowed(db_session) -> None:
    await repo_access.register_repository(db_session, "github", "acme/api")

    status = await repo_access.check_access(
        db_session, "github", "acme/api", reason="need the diff"
    )
    assert status == repo_access.PENDING

    reqs = (await db_session.execute(select(AccessRequest))).scalars().all()
    assert len(reqs) == 1
    assert reqs[0].status == repo_access.PENDING
    assert reqs[0].reason == "need the diff"

    # A second check must not open a duplicate pending request.
    await repo_access.check_access(db_session, "github", "acme/api")
    reqs = (await db_session.execute(select(AccessRequest))).scalars().all()
    assert len(reqs) == 1


@pytest.mark.asyncio
async def test_allowed_repo_does_not_open_request(db_session) -> None:
    repo = await repo_access.register_repository(db_session, "github", "acme/api")
    repo.access_status = repo_access.ALLOWED
    await db_session.commit()

    status = await repo_access.check_access(db_session, "github", "acme/api")
    assert status == repo_access.ALLOWED
    reqs = (await db_session.execute(select(AccessRequest))).scalars().all()
    assert reqs == []


@pytest.mark.asyncio
async def test_credential_round_trip_only_when_allowed(db_session) -> None:
    repo = await repo_access.register_repository(db_session, "github", "acme/api")
    repo_access.set_credential(repo, "github_pat", "ghp_secrettoken_value_1234567890")
    await db_session.commit()

    # Not allowed yet -> no credential handed out.
    assert await repo_access.get_credential(db_session, "github", "acme/api") is None

    repo.access_status = repo_access.ALLOWED
    await db_session.commit()

    cred = await repo_access.get_credential(db_session, "github", "acme/api")
    assert cred is not None
    method, secret = cred
    assert method == "github_pat"
    assert secret == "ghp_secrettoken_value_1234567890"
    assert repo.credential_fingerprint is not None


@pytest.mark.asyncio
async def test_clearing_credential(db_session) -> None:
    repo = await repo_access.register_repository(db_session, "github", "acme/api")
    repo_access.set_credential(repo, "github_pat", "ghp_x_1234567890123456789012")
    repo_access.set_credential(repo, "none", None)
    await db_session.commit()
    assert repo.credential_encrypted is None
    assert repo.auth_method == "none"
