"""
SQLAlchemy 2.0 telemetry models.

These four tables cover the UI's needs:

* ``failures``     — one row per CI event (Jenkins / GitHub / CLI / webhook)
* ``stacktraces``  — the snipped 50-line excerpt(s) tied to a failure
* ``rca_reports``  — the AI's verdict (summary, matched wiki doc, tool trace)
* ``wiki_settings``— one-row config for the Markdown wiki backup target
* ``wiki_backup_log`` — audit trail of push attempts (success / failure)

The RCA fast-path (docs-as-code) never writes anything "knowledge shaped"
here — knowledge lives in the Git-backed wiki, not in the DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    mapped_column,
    relationship,
)


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(MappedAsDataclass, DeclarativeBase):
    """Declarative base. ``MappedAsDataclass`` gives us ergonomic __init__/__repr__."""


class Failure(Base):
    """A CI event that may or may not require RCA."""

    __tablename__ = "failures"

    source: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(32), default="received")
    repo: Mapped[str | None] = mapped_column(String(255), default=None)
    job_name: Mapped[str | None] = mapped_column(String(255), default=None)
    build_number: Mapped[int | None] = mapped_column(default=None)
    run_id: Mapped[int | None] = mapped_column(default=None)
    pr_number: Mapped[str | None] = mapped_column(String(64), default=None)
    commit_sha: Mapped[str | None] = mapped_column(String(64), default=None)
    branch: Mapped[str | None] = mapped_column(String(255), default=None)
    build_url: Mapped[str | None] = mapped_column(Text, default=None)
    task_id: Mapped[str | None] = mapped_column(String(64), default=None)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, init=False, default_factory=_uuid)
    triggered_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
    )

    stacktraces: Mapped[list[Stacktrace]] = relationship(
        back_populates="failure",
        cascade="all, delete-orphan",
        init=False,
    )
    rca_reports: Mapped[list[RcaReport]] = relationship(
        back_populates="failure",
        cascade="all, delete-orphan",
        init=False,
    )
    commit_diffs: Mapped[list[CommitDiff]] = relationship(
        back_populates="failure",
        cascade="all, delete-orphan",
        init=False,
    )

    __table_args__ = (
        Index("ix_failures_source_triggered", "source", "triggered_at"),
        Index("ix_failures_task_id", "task_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Shape consumed by the React portal's FailuresList."""
        latest_rca = self.rca_reports[-1] if self.rca_reports else None
        return {
            "id": self.id,
            "source": self.source,
            "status": self.status,
            "repo": self.repo,
            "job_name": self.job_name,
            "build_number": self.build_number,
            "run_id": self.run_id,
            "pr_number": self.pr_number,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "build_url": self.build_url,
            "task_id": self.task_id,
            "triggered_at": (
                self.triggered_at.isoformat() if self.triggered_at is not None else None
            ),
            "rca_summary": latest_rca.summary if latest_rca is not None else None,
        }


class Stacktrace(Base):
    """A snipped log excerpt attached to a failure (typically <=50 lines)."""

    __tablename__ = "stacktraces"

    failure_id: Mapped[str] = mapped_column(
        ForeignKey("failures.id", ondelete="CASCADE"),
    )
    excerpt: Mapped[str] = mapped_column(Text)

    line_count: Mapped[int] = mapped_column(default=0)
    language: Mapped[str | None] = mapped_column(String(32), default=None)
    # Complete captured log. ``excerpt`` stays the trimmed preview so existing
    # list views remain cheap; ``full_text`` holds the untruncated payload.
    full_text: Mapped[str | None] = mapped_column(Text, default=None)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, init=False, default_factory=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
    )

    failure: Mapped[Failure] = relationship(back_populates="stacktraces", init=False)


class RcaReport(Base):
    """The AI's verdict for a failure. Multiple reports per failure are allowed
    (re-runs, human overrides) — the UI shows the most recent."""

    __tablename__ = "rca_reports"

    failure_id: Mapped[str] = mapped_column(
        ForeignKey("failures.id", ondelete="CASCADE"),
    )
    summary: Mapped[str] = mapped_column(Text)
    branch_taken: Mapped[str] = mapped_column(String(32))  # "wiki_hit" | "novel_reasoned"

    wiki_doc_path: Mapped[str | None] = mapped_column(String(512), default=None)
    wiki_doc_created: Mapped[bool] = mapped_column(default=False)
    tool_trace: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None)
    model_used: Mapped[str | None] = mapped_column(String(128), default=None)
    latency_ms: Mapped[int | None] = mapped_column(default=None)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, init=False, default_factory=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
    )

    failure: Mapped[Failure] = relationship(back_populates="rca_reports", init=False)


class WikiSettings(Base):
    """Single-row configuration for the wiki's optional remote backup.

    Only id=1 is used. Kept in Postgres (not env) so engineers can change
    the backup target via the portal without redeploying.
    """

    __tablename__ = "wiki_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(default=False)
    remote_url: Mapped[str | None] = mapped_column(String(512), default=None)
    remote_branch: Mapped[str] = mapped_column(String(128), default="main")
    auto_backup_hours: Mapped[int | None] = mapped_column(default=None)
    deploy_key_encrypted: Mapped[bytes | None] = mapped_column(default=None)
    deploy_key_fingerprint: Mapped[str | None] = mapped_column(String(128), default=None)
    last_backup_at: Mapped[datetime | None] = mapped_column(default=None)
    last_backup_status: Mapped[str | None] = mapped_column(String(32), default=None)
    last_backup_message: Mapped[str | None] = mapped_column(Text, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
        server_onupdate=func.now(),
    )


class WikiBackupLog(Base):
    """Audit trail of every push attempt — surfaced in the portal."""

    __tablename__ = "wiki_backup_log"

    status: Mapped[str] = mapped_column(String(32))

    message: Mapped[str | None] = mapped_column(Text, default=None)
    triggered_by: Mapped[str] = mapped_column(String(32), default="auto")

    id: Mapped[str] = mapped_column(String(32), primary_key=True, init=False, default_factory=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
    )


class CommitDiff(Base):
    """The unified diff of the change that most likely caused a failure.

    We store only the *latest* diff (failing commit or PR) per failure — full
    repository indexing is intentionally out of scope. ``patch`` may be
    truncated for very large changes; ``truncated`` records that.
    """

    __tablename__ = "commit_diffs"

    failure_id: Mapped[str] = mapped_column(
        ForeignKey("failures.id", ondelete="CASCADE"),
    )
    provider: Mapped[str] = mapped_column(String(32))

    ref: Mapped[str | None] = mapped_column(String(128), default=None)
    files_changed: Mapped[int] = mapped_column(default=0)
    additions: Mapped[int] = mapped_column(default=0)
    deletions: Mapped[int] = mapped_column(default=0)
    patch: Mapped[str | None] = mapped_column(Text, default=None)
    truncated: Mapped[bool] = mapped_column(default=False)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, init=False, default_factory=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
    )

    failure: Mapped[Failure] = relationship(back_populates="commit_diffs", init=False)


class Repository(Base):
    """A code/CI source Tracebow knows about, plus its outbound-access grant.

    Ingress (a CI pipeline pushing logs to us) is always accepted. This row
    governs *outbound* access: whether the agent may call back out to the
    provider (fetch diffs, read PRs, query builds) for this repo/job.
    """

    __tablename__ = "repositories"

    provider: Mapped[str] = mapped_column(String(32))
    identifier: Mapped[str] = mapped_column(String(512))

    display_name: Mapped[str | None] = mapped_column(String(512), default=None)
    # allowed | denied | pending
    access_status: Mapped[str] = mapped_column(String(16), default="pending")
    # none | github_pat | ssh_deploy_key | github_app | oauth
    auth_method: Mapped[str] = mapped_column(String(32), default="none")
    credential_encrypted: Mapped[bytes | None] = mapped_column(default=None)
    credential_fingerprint: Mapped[str | None] = mapped_column(String(128), default=None)
    last_seen_at: Mapped[datetime | None] = mapped_column(default=None)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, init=False, default_factory=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
        server_onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("provider", "identifier", name="uq_repositories_provider_identifier"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "identifier": self.identifier,
            "display_name": self.display_name,
            "access_status": self.access_status,
            "auth_method": self.auth_method,
            "has_credential": self.credential_encrypted is not None,
            "credential_fingerprint": self.credential_fingerprint,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
        }


class AccessRequest(Base):
    """A pending ask to grant outbound access to a repo/job.

    Created by the access gate (or, once the LLM reason node lands, by the
    agent itself via the ``request_access`` tool) whenever a needed source is
    not yet ``allowed``. A human approves or denies it from the portal.
    """

    __tablename__ = "access_requests"

    provider: Mapped[str] = mapped_column(String(32))
    identifier: Mapped[str] = mapped_column(String(512))

    repository_id: Mapped[str | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"),
        default=None,
    )
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    # pending | approved | denied
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requested_by: Mapped[str] = mapped_column(String(32), default="agent")
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, init=False, default_factory=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "identifier": self.identifier,
            "repository_id": self.repository_id,
            "reason": self.reason,
            "status": self.status,
            "requested_by": self.requested_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
        }


class EgressEvent(Base):
    """One record per outbound network attempt — the security dashboard's data.

    Recorded at the two egress choke points (the shared HTTP helper and the
    wiki push). ``destination_kind`` distinguishes internal infra (ollama,
    postgres, redis) from genuinely external hosts (github, slack, ...).
    """

    __tablename__ = "egress_events"

    destination_host: Mapped[str] = mapped_column(String(255))
    destination_kind: Mapped[str] = mapped_column(String(16))  # internal | external

    purpose: Mapped[str | None] = mapped_column(String(128), default=None)
    method: Mapped[str | None] = mapped_column(String(16), default=None)
    request_bytes: Mapped[int] = mapped_column(default=0)
    response_bytes: Mapped[int] = mapped_column(default=0)
    status: Mapped[str | None] = mapped_column(String(32), default=None)
    # none_as_null so "no flags" is SQL NULL (queryable), not a JSON ``null``.
    sensitive_flags: Mapped[list[str] | None] = mapped_column(JSON(none_as_null=True), default=None)
    blocked: Mapped[bool] = mapped_column(default=False)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, init=False, default_factory=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        init=False,
        default=None,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_egress_events_created", "created_at"),
        Index("ix_egress_events_kind", "destination_kind"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "destination_host": self.destination_host,
            "destination_kind": self.destination_kind,
            "purpose": self.purpose,
            "method": self.method,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "status": self.status,
            "sensitive_flags": self.sensitive_flags or [],
            "blocked": self.blocked,
            "created_at": self.created_at.isoformat() if self.created_at is not None else None,
        }
