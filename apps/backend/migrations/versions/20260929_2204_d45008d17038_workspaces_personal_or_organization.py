"""workspaces personal or organization

Organisations fold into workspaces (docs/agents-v2.md §0, D6): a workspace is personal or an
organisation. Team and business workspaces become organisations; an organisation's owner who
saw a workspace only through the organisation becomes its owner; the organisations layer goes.

Revision ID: d45008d17038
Revises: 3b73b89797fa
Create Date: 2026-09-29 22:04:10.390008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d45008d17038"
down_revision: str | None = "3b73b89797fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("workspacekind", "workspaces", type_="check")
    op.execute("UPDATE workspaces SET kind = 'organization' WHERE kind IN ('team', 'business')")
    op.create_check_constraint(
        "workspacekind", "workspaces", "kind IN ('personal', 'organization')"
    )
    # Org owners had implicit owner access to their organisation's workspaces: make it real.
    op.execute(
        """
        INSERT INTO memberships (id, workspace_id, user_id, role, created_at, updated_at)
        SELECT gen_random_uuid(), w.id, om.user_id, 'owner', now(), now()
        FROM workspaces w
        JOIN org_memberships om ON om.organization_id = w.organization_id AND om.role = 'owner'
        WHERE NOT EXISTS (
            SELECT 1 FROM memberships m WHERE m.workspace_id = w.id AND m.user_id = om.user_id
        )
        """
    )
    op.drop_index(op.f("ix_workspaces_organization_id"), table_name="workspaces")
    op.drop_constraint(
        op.f("fk_workspaces_organization_id_organizations"), "workspaces", type_="foreignkey"
    )
    op.drop_column("workspaces", "organization_id")
    op.drop_index(op.f("ix_org_memberships_organization_id"), table_name="org_memberships")
    op.drop_index(op.f("ix_org_memberships_user_id"), table_name="org_memberships")
    op.drop_table("org_memberships")
    op.drop_index(op.f("ix_organizations_slug"), table_name="organizations")
    op.drop_table("organizations")


def downgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column("slug", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("created_by_id", sa.UUID(), autoincrement=False, nullable=True),
        sa.Column("id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_organizations_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_index(op.f("ix_organizations_slug"), "organizations", ["slug"], unique=True)
    op.create_table(
        "org_memberships",
        sa.Column("organization_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("role", sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column("id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.CheckConstraint(
            "role::text = ANY (ARRAY['owner'::character varying, 'admin'::character varying, 'member'::character varying]::text[])",
            name=op.f("ck_org_memberships_orgrole"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_org_memberships_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_org_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_memberships")),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name=op.f("uq_org_memberships_organization_id_user_id"),
            postgresql_include=[],
            postgresql_nulls_not_distinct=False,
        ),
    )
    op.create_index(
        op.f("ix_org_memberships_user_id"), "org_memberships", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_org_memberships_organization_id"),
        "org_memberships",
        ["organization_id"],
        unique=False,
    )
    op.add_column(
        "workspaces", sa.Column("organization_id", sa.UUID(), autoincrement=False, nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_workspaces_organization_id_organizations"),
        "workspaces",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_workspaces_organization_id"), "workspaces", ["organization_id"], unique=False
    )
    op.drop_constraint("workspacekind", "workspaces", type_="check")
    op.execute("UPDATE workspaces SET kind = 'team' WHERE kind = 'organization'")
    op.create_check_constraint(
        "workspacekind", "workspaces", "kind IN ('personal', 'team', 'business')"
    )
