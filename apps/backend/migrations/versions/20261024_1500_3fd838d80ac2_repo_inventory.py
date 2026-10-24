"""Repository inventories: snapshots of a connected repo's tracked paths at a commit, each classified.

Revision ID: 3fd838d80ac2
Revises: 689242032225
Create Date: 2026-10-24 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3fd838d80ac2"
down_revision: str | None = "689242032225"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repo_snapshots",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("repo_full_name", sa.String(length=200), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("path_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_repo_snapshots_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_repo_snapshots_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repo_snapshots")),
        sa.UniqueConstraint(
            "project_id",
            "commit_sha",
            "policy_version",
            name=op.f("uq_repo_snapshots_project_id_commit_sha_policy_version"),
        ),
    )
    op.create_index(
        op.f("ix_repo_snapshots_project_id"), "repo_snapshots", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_repo_snapshots_workspace_id"), "repo_snapshots", ["workspace_id"], unique=False
    )
    op.create_table(
        "repo_paths",
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("blob", sa.String(length=40), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("kinds", postgresql.ARRAY(sa.String(length=24)), nullable=False),
        sa.Column("domains", postgresql.ARRAY(sa.String(length=24)), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "analyzed",
                "excluded",
                "unsupported",
                "inaccessible",
                name="pathstatus",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analyzed_run_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["repo_snapshots.id"],
            name=op.f("fk_repo_paths_snapshot_id_repo_snapshots"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_repo_paths_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repo_paths")),
        sa.UniqueConstraint("snapshot_id", "path", name=op.f("uq_repo_paths_snapshot_id_path")),
    )
    op.create_index(
        "ix_repo_paths_snapshot_status", "repo_paths", ["snapshot_id", "status"], unique=False
    )
    op.create_index(
        op.f("ix_repo_paths_workspace_id"), "repo_paths", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_repo_paths_workspace_id"), table_name="repo_paths")
    op.drop_index("ix_repo_paths_snapshot_status", table_name="repo_paths")
    op.drop_table("repo_paths")
    op.drop_index(op.f("ix_repo_snapshots_workspace_id"), table_name="repo_snapshots")
    op.drop_index(op.f("ix_repo_snapshots_project_id"), table_name="repo_snapshots")
    op.drop_table("repo_snapshots")
