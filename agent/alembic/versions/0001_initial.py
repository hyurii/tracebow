"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-20 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "failures",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("repo", sa.String(255)),
        sa.Column("job_name", sa.String(255)),
        sa.Column("build_number", sa.Integer()),
        sa.Column("run_id", sa.Integer()),
        sa.Column("pr_number", sa.String(64)),
        sa.Column("commit_sha", sa.String(64)),
        sa.Column("branch", sa.String(255)),
        sa.Column("build_url", sa.Text()),
        sa.Column("task_id", sa.String(64)),
        sa.Column(
            "triggered_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_failures_source_triggered", "failures", ["source", "triggered_at"])
    op.create_index("ix_failures_task_id", "failures", ["task_id"])

    op.create_table(
        "stacktraces",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "failure_id",
            sa.String(32),
            sa.ForeignKey("failures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("language", sa.String(32)),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "rca_reports",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "failure_id",
            sa.String(32),
            sa.ForeignKey("failures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("branch_taken", sa.String(32), nullable=False),
        sa.Column("wiki_doc_path", sa.String(512)),
        sa.Column("wiki_doc_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tool_trace", sa.JSON()),
        sa.Column("model_used", sa.String(128)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "wiki_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remote_url", sa.String(512)),
        sa.Column("remote_branch", sa.String(128), nullable=False, server_default="main"),
        sa.Column("auto_backup_hours", sa.Integer()),
        sa.Column("deploy_key_encrypted", sa.LargeBinary()),
        sa.Column("deploy_key_fingerprint", sa.String(128)),
        sa.Column("last_backup_at", sa.DateTime()),
        sa.Column("last_backup_status", sa.String(32)),
        sa.Column("last_backup_message", sa.Text()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "wiki_backup_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("triggered_by", sa.String(32), nullable=False, server_default="auto"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("wiki_backup_log")
    op.drop_table("wiki_settings")
    op.drop_table("rca_reports")
    op.drop_table("stacktraces")
    op.drop_index("ix_failures_task_id", table_name="failures")
    op.drop_index("ix_failures_source_triggered", table_name="failures")
    op.drop_table("failures")
