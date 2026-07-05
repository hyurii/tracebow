"""repo access control + security monitoring foundation

Revision ID: 0002_foundation
Revises: 0001_initial
Create Date: 2026-07-02 00:00:00.000000

Adds:
* ``stacktraces.full_text`` — untruncated captured log.
* ``commit_diffs`` — latest failing diff per failure.
* ``repositories`` — outbound-access registry + encrypted credentials.
* ``access_requests`` — pending grants awaiting human approval.
* ``egress_events`` — audit trail for the security dashboard.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0002_foundation"
down_revision: str | None = "0001_initial"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("stacktraces", sa.Column("full_text", sa.Text(), nullable=True))

    op.create_table(
        "commit_diffs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "failure_id",
            sa.String(32),
            sa.ForeignKey("failures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("ref", sa.String(128)),
        sa.Column("files_changed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("additions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("patch", sa.Text()),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "repositories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("identifier", sa.String(512), nullable=False),
        sa.Column("display_name", sa.String(512)),
        sa.Column("access_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("auth_method", sa.String(32), nullable=False, server_default="none"),
        sa.Column("credential_encrypted", sa.LargeBinary()),
        sa.Column("credential_fingerprint", sa.String(128)),
        sa.Column("last_seen_at", sa.DateTime()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("provider", "identifier", name="uq_repositories_provider_identifier"),
    )

    op.create_table(
        "access_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("identifier", sa.String(512), nullable=False),
        sa.Column(
            "repository_id",
            sa.String(32),
            sa.ForeignKey("repositories.id", ondelete="SET NULL"),
        ),
        sa.Column("reason", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(32), nullable=False, server_default="agent"),
        sa.Column("resolved_at", sa.DateTime()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "egress_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("destination_host", sa.String(255), nullable=False),
        sa.Column("destination_kind", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(128)),
        sa.Column("method", sa.String(16)),
        sa.Column("request_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32)),
        sa.Column("sensitive_flags", sa.JSON()),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_egress_events_created", "egress_events", ["created_at"])
    op.create_index("ix_egress_events_kind", "egress_events", ["destination_kind"])


def downgrade() -> None:
    op.drop_index("ix_egress_events_kind", table_name="egress_events")
    op.drop_index("ix_egress_events_created", table_name="egress_events")
    op.drop_table("egress_events")
    op.drop_table("access_requests")
    op.drop_table("repositories")
    op.drop_table("commit_diffs")
    op.drop_column("stacktraces", "full_text")
