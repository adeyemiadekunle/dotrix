"""Allow repository-backed coding sessions without an issue."""

import sqlalchemy as sa
from alembic import op

revision = "c0d146a04602"
down_revision = "c3a91f02d7e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("coding_runs", "issue_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("coding_sessions", "issue_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("coding_runs", sa.Column("task_title", sa.String(200)))
    op.add_column("coding_runs", sa.Column("source_sha", sa.String(40)))
    op.add_column("coding_runs", sa.Column("source_repo_id", sa.BigInteger()))


def downgrade() -> None:
    # Issue-less sessions cannot be represented on the previous schema.
    op.alter_column("coding_sessions", "issue_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("coding_runs", "issue_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("coding_runs", "source_repo_id")
    op.drop_column("coding_runs", "source_sha")
    op.drop_column("coding_runs", "task_title")
