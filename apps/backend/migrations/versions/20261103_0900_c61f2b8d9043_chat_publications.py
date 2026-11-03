"""Private, idempotent chat outcome publication records."""
import sqlalchemy as sa
from alembic import op

revision = "c61f2b8d9043"
down_revision = "b50e1a9c7632"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "chat_publications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("destination", sa.String(16), nullable=False),
        sa.Column("target", sa.String(500), nullable=False),
        sa.UniqueConstraint("project_id", "user_id", "request_id"),
    )
    op.create_index("ix_chat_publications_workspace_id", "chat_publications", ["workspace_id"])


def downgrade():
    op.drop_table("chat_publications")
