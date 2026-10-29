"""Pin the selected chat runtime on each agent run."""
import sqlalchemy as sa
from alembic import op

revision = "8b4c7a1e952f"
down_revision = "6cf58b7d214a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_runs", sa.Column("chat_runtime", sa.String(16), nullable=False, server_default="deepagents"))
    op.create_check_constraint(op.f("ck_agent_runs_chatruntime"), "agent_runs", "chat_runtime IN ('deepagents','fx')")


def downgrade():
    op.drop_constraint(op.f("ck_agent_runs_chatruntime"), "agent_runs", type_="check")
    op.drop_column("agent_runs", "chat_runtime")
