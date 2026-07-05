"""Repository outbound-access control.

Ingress (a CI pipeline pushing logs to Tracebow) is always accepted. This
module governs the *outbound* direction: whether the agent may call back out
to a provider (fetch a diff, read a PR, query builds) for a given repo/job.

Flow:
* Every failure auto-registers its source as a :class:`Repository` row
  (``last_seen_at`` bumped). New sources default to ``pending``.
* Before any outbound call for a source, callers consult :func:`check_access`.
  When the source is not ``allowed``, an :class:`AccessRequest` is opened so a
  human can grant it from the portal.
* Credentials (a GitHub PAT or an SSH deploy key) are encrypted at rest with
  the same Fernet key used for the wiki deploy key.

The async functions operate on a caller-supplied session; the ``*_sync``
wrappers spin a short-lived event loop for the sync Celery/LangGraph paths,
mirroring the pattern in :mod:`tracebow.tasks`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracebow.db import AccessRequest, Repository, get_session_factory
from tracebow.services.secrets import decrypt, encrypt, fingerprint

logger = logging.getLogger(__name__)

ALLOWED = "allowed"
DENIED = "denied"
PENDING = "pending"

VALID_STATUSES = frozenset({ALLOWED, DENIED, PENDING})
VALID_AUTH_METHODS = frozenset({"none", "github_pat", "ssh_deploy_key", "github_app", "oauth"})
# Auth methods actually implemented today; the rest are reserved for phase 2.
IMPLEMENTED_AUTH_METHODS = frozenset({"none", "github_pat", "ssh_deploy_key"})


def derive_source(event_type: str, payload: dict[str, Any]) -> tuple[str, str] | None:
    """Map an RCA event to a ``(provider, identifier)`` outbound source.

    Returns ``None`` when the event carries nothing we could call back out to.
    """
    if event_type == "jenkins":
        job = payload.get("job_name")
        return ("jenkins", str(job)) if job else None
    # github / cli both target a GitHub repository
    repo = payload.get("repository") or payload.get("repo")
    if repo:
        return ("github", str(repo))
    return None


async def register_repository(
    session: AsyncSession,
    provider: str,
    identifier: str,
    display_name: str | None = None,
) -> Repository:
    """Idempotently upsert a repository and bump ``last_seen_at``."""
    row = (
        (
            await session.execute(
                select(Repository).where(
                    Repository.provider == provider,
                    Repository.identifier == identifier,
                )
            )
        )
        .scalars()
        .first()
    )
    now = dt.datetime.utcnow()
    if row is None:
        row = Repository(
            provider=provider,
            identifier=identifier,
            display_name=display_name or identifier,
        )
        row.last_seen_at = now
        session.add(row)
    else:
        row.last_seen_at = now
        if display_name and not row.display_name:
            row.display_name = display_name
    await session.commit()
    await session.refresh(row)
    return row


async def get_access_status(session: AsyncSession, provider: str, identifier: str) -> str:
    """Return the stored status, or ``pending`` when unknown."""
    row = (
        (
            await session.execute(
                select(Repository).where(
                    Repository.provider == provider,
                    Repository.identifier == identifier,
                )
            )
        )
        .scalars()
        .first()
    )
    return row.access_status if row is not None else PENDING


async def ensure_access_request(
    session: AsyncSession,
    provider: str,
    identifier: str,
    reason: str | None = None,
    requested_by: str = "agent",
) -> AccessRequest:
    """Open a pending access request if one is not already outstanding."""
    existing = (
        (
            await session.execute(
                select(AccessRequest).where(
                    AccessRequest.provider == provider,
                    AccessRequest.identifier == identifier,
                    AccessRequest.status == PENDING,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing

    repo = (
        (
            await session.execute(
                select(Repository).where(
                    Repository.provider == provider,
                    Repository.identifier == identifier,
                )
            )
        )
        .scalars()
        .first()
    )

    req = AccessRequest(
        provider=provider,
        identifier=identifier,
        reason=reason,
        requested_by=requested_by,
    )
    if repo is not None:
        req.repository_id = repo.id
    session.add(req)
    await session.commit()
    await session.refresh(req)
    logger.info("Opened access request for %s:%s", provider, identifier)
    return req


async def check_access(
    session: AsyncSession,
    provider: str,
    identifier: str,
    reason: str | None = None,
    requested_by: str = "agent",
) -> str:
    """Return the access status; open a request when not ``allowed``."""
    status = await get_access_status(session, provider, identifier)
    if status != ALLOWED:
        await ensure_access_request(
            session, provider, identifier, reason=reason, requested_by=requested_by
        )
    return status


async def get_credential(
    session: AsyncSession, provider: str, identifier: str
) -> tuple[str, str] | None:
    """Return ``(auth_method, secret)`` for an allowed repo, else ``None``."""
    row = (
        (
            await session.execute(
                select(Repository).where(
                    Repository.provider == provider,
                    Repository.identifier == identifier,
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None or row.access_status != ALLOWED:
        return None
    if not row.credential_encrypted or row.auth_method == "none":
        return None
    try:
        secret = decrypt(row.credential_encrypted)
    except ValueError:
        logger.warning("Could not decrypt credential for %s:%s", provider, identifier)
        return None
    return (row.auth_method, secret)


def set_credential(row: Repository, auth_method: str, secret: str | None) -> None:
    """Mutate a repository row's credential fields (encrypting the secret)."""
    row.auth_method = auth_method if auth_method in VALID_AUTH_METHODS else "none"
    if secret:
        row.credential_encrypted = encrypt(secret)
        row.credential_fingerprint = fingerprint(secret)
    else:
        row.credential_encrypted = None
        row.credential_fingerprint = None
        if auth_method == "none":
            row.auth_method = "none"


# ---------------------------------------------------------------------------
# Sync bridges for Celery tasks / LangGraph tools
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def register_repository_sync(
    provider: str, identifier: str, display_name: str | None = None
) -> None:
    async def _inner() -> None:
        sm = get_session_factory()
        async with sm() as session:
            await register_repository(session, provider, identifier, display_name)

    try:
        _run(_inner())
    except Exception:
        logger.exception("register_repository_sync failed for %s:%s", provider, identifier)


def check_access_sync(provider: str, identifier: str, reason: str | None = None) -> str:
    async def _inner() -> str:
        sm = get_session_factory()
        async with sm() as session:
            return await check_access(session, provider, identifier, reason=reason)

    try:
        result: str = _run(_inner())
        return result
    except Exception:
        logger.exception("check_access_sync failed for %s:%s", provider, identifier)
        return PENDING


def get_credential_sync(provider: str, identifier: str) -> tuple[str, str] | None:
    async def _inner() -> tuple[str, str] | None:
        sm = get_session_factory()
        async with sm() as session:
            return await get_credential(session, provider, identifier)

    try:
        result: tuple[str, str] | None = _run(_inner())
        return result
    except Exception:
        logger.exception("get_credential_sync failed for %s:%s", provider, identifier)
        return None


def request_access_sync(
    provider: str, identifier: str, reason: str | None = None
) -> dict[str, Any]:
    async def _inner() -> dict[str, Any]:
        sm = get_session_factory()
        async with sm() as session:
            status = await get_access_status(session, provider, identifier)
            if status == ALLOWED:
                return {"status": "already_allowed", "provider": provider, "identifier": identifier}
            req = await ensure_access_request(
                session, provider, identifier, reason=reason, requested_by="agent"
            )
            return {
                "status": "requested",
                "provider": provider,
                "identifier": identifier,
                "request_id": req.id,
            }

    try:
        result: dict[str, Any] = _run(_inner())
        return result
    except Exception as exc:
        logger.exception("request_access_sync failed for %s:%s", provider, identifier)
        return {"status": "error", "error": str(exc)}
