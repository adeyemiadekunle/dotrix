"""Run events keep Nova's thinking (kind "thinking")."""
from alembic import op

revision = "3c7d9e1f5a42"
down_revision = "5b819b79e64b"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f("ck_agent_run_events_runeventkind"), "agent_run_events", type_="check")
    op.create_check_constraint(op.f("ck_agent_run_events_runeventkind"), "agent_run_events",
                               "kind IN ('step','text','activity','thinking','status','task')")


def downgrade():
    op.execute("DELETE FROM agent_run_events WHERE kind = 'thinking'")
    op.drop_constraint(op.f("ck_agent_run_events_runeventkind"), "agent_run_events", type_="check")
    op.create_check_constraint(op.f("ck_agent_run_events_runeventkind"), "agent_run_events",
                               "kind IN ('step','text','activity','status','task')")
