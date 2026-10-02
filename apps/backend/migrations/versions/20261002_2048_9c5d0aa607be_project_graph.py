"""project graph

Revision ID: 9c5d0aa607be
Revises: 4c2fa83f7d22
Create Date: 2026-10-02 20:48:08.231228
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c5d0aa607be"
down_revision: str | None = "4c2fa83f7d22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "document",
                "issue",
                "module",
                name="nodekind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("ref", sa.String(length=300), nullable=False),
        sa.Column("subtype", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("issue_id", sa.Uuid(), nullable=True),
        sa.Column("synced_version", sa.Integer(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["knowledge_files.id"],
            name=op.f("fk_graph_nodes_file_id_knowledge_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name=op.f("fk_graph_nodes_issue_id_issues"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_graph_nodes_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_graph_nodes_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_nodes")),
        sa.UniqueConstraint("project_id", "ref", name=op.f("uq_graph_nodes_project_id_ref")),
    )
    op.create_index(op.f("ix_graph_nodes_file_id"), "graph_nodes", ["file_id"], unique=False)
    op.create_index(op.f("ix_graph_nodes_issue_id"), "graph_nodes", ["issue_id"], unique=False)
    op.create_index(op.f("ix_graph_nodes_project_id"), "graph_nodes", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_graph_nodes_workspace_id"), "graph_nodes", ["workspace_id"], unique=False
    )
    op.create_table(
        "graph_edges",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("target_ref", sa.String(length=300), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "implements",
                "depends_on",
                "part_of",
                "decided_by",
                "affects",
                "supersedes",
                "mentions",
                "relates_to",
                name="edgekind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "origin",
            sa.Enum(
                "derived",
                "person",
                "agent",
                name="edgeorigin",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("agent", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_graph_edges_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_graph_edges_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_edges_source_id_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_edges_target_id_graph_nodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_graph_edges_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_edges")),
        sa.UniqueConstraint(
            "source_id", "target_ref", "kind", name=op.f("uq_graph_edges_source_id_target_ref_kind")
        ),
    )
    op.create_index(op.f("ix_graph_edges_project_id"), "graph_edges", ["project_id"], unique=False)
    op.create_index(
        "ix_graph_edges_project_id_target_ref",
        "graph_edges",
        ["project_id", "target_ref"],
        unique=False,
    )
    op.create_index(op.f("ix_graph_edges_source_id"), "graph_edges", ["source_id"], unique=False)
    op.create_index(op.f("ix_graph_edges_target_id"), "graph_edges", ["target_id"], unique=False)
    op.create_index(
        op.f("ix_graph_edges_workspace_id"), "graph_edges", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_graph_edges_workspace_id"), table_name="graph_edges")
    op.drop_index(op.f("ix_graph_edges_target_id"), table_name="graph_edges")
    op.drop_index(op.f("ix_graph_edges_source_id"), table_name="graph_edges")
    op.drop_index("ix_graph_edges_project_id_target_ref", table_name="graph_edges")
    op.drop_index(op.f("ix_graph_edges_project_id"), table_name="graph_edges")
    op.drop_table("graph_edges")
    op.drop_index(op.f("ix_graph_nodes_workspace_id"), table_name="graph_nodes")
    op.drop_index(op.f("ix_graph_nodes_project_id"), table_name="graph_nodes")
    op.drop_index(op.f("ix_graph_nodes_issue_id"), table_name="graph_nodes")
    op.drop_index(op.f("ix_graph_nodes_file_id"), table_name="graph_nodes")
    op.drop_table("graph_nodes")
