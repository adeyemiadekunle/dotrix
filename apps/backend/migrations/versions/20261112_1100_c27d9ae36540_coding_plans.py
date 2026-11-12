"""Persist coding Plan turns and their private results."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c27d9ae36540"
down_revision = "b16c8fd25439"
branch_labels = depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("skill_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("coding_runs", sa.Column("skill_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("coding_runs", sa.Column("work_mode", sa.String(8), nullable=False, server_default="build"))
    op.add_column("coding_runs", sa.Column("plan_result", postgresql.JSONB(), nullable=True))


    op.add_column("coding_runs", sa.Column("execution_plan", postgresql.JSONB(), nullable=True))
    op.add_column("coding_runs", sa.Column("task_records", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("coding_runs", "skill_snapshot")
    op.drop_column("agent_runs", "skill_snapshot")
    op.drop_column("coding_runs", "task_records")
    op.drop_column("coding_runs", "execution_plan")
    op.drop_column("coding_runs", "plan_result")
    op.drop_column("coding_runs", "work_mode")
