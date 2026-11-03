"""Record human reviews of a repository's exact baseline evidence."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d40a7c2e9186"
down_revision = "9c4e7a1b2d63"
branch_labels = depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("repository_write_paths", postgresql.JSONB(), nullable=True))
    op.create_table("repo_baseline_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("project_id", "request_id"),
    )
    op.create_index("ix_repo_baseline_reviews_workspace_id", "repo_baseline_reviews", ["workspace_id"])
    op.create_index("ix_repo_baseline_reviews_project_id", "repo_baseline_reviews", ["project_id"])


def downgrade():
    op.drop_table("repo_baseline_reviews")
    op.drop_column("agent_runs", "repository_write_paths")
