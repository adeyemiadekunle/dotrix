"""Reviewed GitHub backlog snapshots and permanent import identities."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d72e4b9c6105"
down_revision = "c61f2b8d9043"
branch_labels = depends_on = None


def common():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("github_import_previews", *common(),
        sa.Column("requested_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("binding_id", sa.Uuid(), sa.ForeignKey("connected_repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("selection_digest", sa.String(64)), sa.Column("result", postgresql.JSONB()),
    )
    op.create_table("github_imported_issues", *common(),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("github_issue_id", sa.BigInteger(), nullable=False),
        sa.Column("source_number", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("issue_id", sa.Uuid(), sa.ForeignKey("issues.id", ondelete="SET NULL")),
        sa.Column("issue_key", sa.String(24), nullable=False),
        sa.Column("imported_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.UniqueConstraint("project_id", "github_repo_id", "github_issue_id"),
    )
    for table in ("github_import_previews", "github_imported_issues"):
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])


def downgrade():
    op.drop_table("github_imported_issues")
    op.drop_table("github_import_previews")
