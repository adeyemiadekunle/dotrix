"""Host secrets: a project's credentials for hosts in its network policy, kept out of the sandbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c0d146a04610"
down_revision = "c0d146a04609"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coding_secrets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("host", sa.String(260), nullable=False),
        sa.Column("header", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(32), nullable=False),
        sa.Column("encrypted", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name"),
    )
    op.create_index("ix_coding_secrets_workspace_id", "coding_secrets", ["workspace_id"])
    op.create_index("ix_coding_secrets_project_id", "coding_secrets", ["project_id"])
    op.add_column("coding_runs", sa.Column("secret_snapshot", postgresql.JSONB(none_as_null=True), nullable=True))


def downgrade() -> None:
    op.drop_column("coding_runs", "secret_snapshot")
    op.drop_index("ix_coding_secrets_project_id", table_name="coding_secrets")
    op.drop_index("ix_coding_secrets_workspace_id", table_name="coding_secrets")
    op.drop_table("coding_secrets")
