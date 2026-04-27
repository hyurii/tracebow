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
