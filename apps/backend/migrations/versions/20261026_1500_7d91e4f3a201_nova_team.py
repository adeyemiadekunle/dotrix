"""Durable built-in team tasks; retire custom identities without deleting history."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "7d91e4f3a201"
down_revision = "e5a9c3b2d716"
branch_labels = None
depends_on = None

HANDLES = "'project-manager','product','architecture','research','reviewer','documentation'"


def upgrade():
    op.add_column("agent_preferences", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "agent_preference_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("handle", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.String(2000), nullable=False, server_default=""),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", "handle", "version"),
    )
    op.create_index("ix_agent_preference_versions_workspace_id", "agent_preference_versions", ["workspace_id"])
    op.create_index("ix_agent_preference_versions_user_id", "agent_preference_versions", ["user_id"])
    op.execute("INSERT INTO agent_preference_versions (id, workspace_id, user_id, handle, version, instructions, model, created_at) "
               "SELECT id, workspace_id, user_id, handle, 1, instructions, model, updated_at FROM agent_preferences")
    for column in (
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("delegation_key", sa.String(200), nullable=True),
        sa.Column("task_key", sa.String(40), nullable=True),
        sa.Column("depends_on", postgresql.JSONB(), nullable=True),
        sa.Column("task_mutates", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("task_result", postgresql.JSONB(), nullable=True),
        sa.Column("waiting_interrupts", postgresql.JSONB(), nullable=True),
        sa.Column("orchestration", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source", sa.String(24), nullable=False, server_default="user"),
        sa.Column("outcome_key", sa.String(160), nullable=True),
        sa.Column("review_context", postgresql.JSONB(), nullable=True),
    ):
        op.add_column("agent_runs", column)
    op.create_foreign_key(None, "agent_runs", "agent_runs", ["parent_run_id"], ["id"])
    op.create_index("ix_agent_runs_parent_run_id", "agent_runs", ["parent_run_id"])
    op.create_unique_constraint(None, "agent_runs", ["parent_run_id", "delegation_key", "task_key"])
    op.create_unique_constraint(None, "agent_runs", ["outcome_key"])
    op.drop_constraint(op.f("ck_agent_runs_runstatus"), "agent_runs", type_="check")
    op.create_check_constraint(op.f("ck_agent_runs_runstatus"), "agent_runs",
                               "status IN ('queued','running','awaiting_approval','completed','failed',"
                               "'waiting_children','waiting_dependency','blocked','cancelled')")
    op.drop_constraint(op.f("ck_agent_run_events_runeventkind"), "agent_run_events", type_="check")
    op.create_check_constraint(op.f("ck_agent_run_events_runeventkind"), "agent_run_events",
                               "kind IN ('step','text','activity','status','task')")
    op.add_column("coding_runs", sa.Column("origin_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(None, "coding_runs", "agent_runs", ["origin_run_id"], ["id"])
    op.execute(sa.text(f"UPDATE agent_definitions SET archived_at = now() WHERE handle NOT IN ({HANDLES},'coding-agent') AND archived_at IS NULL"))
    op.execute(sa.text(f"UPDATE automations SET enabled = false, last_error = 'Custom agents are no longer supported; select a built-in agent' WHERE agent IS NOT NULL AND agent NOT IN ({HANDLES},'auto')"))
    op.execute(sa.text(f"UPDATE agent_approvals SET status = 'rejected', reason = 'Custom agent retired' WHERE status = 'pending' AND run_id IN (SELECT id FROM agent_runs WHERE agent IS NOT NULL AND agent NOT IN ({HANDLES},'auto'))"))
    op.execute(sa.text(f"UPDATE agent_runs SET status = 'cancelled', error = 'Custom agents are no longer supported', finished_at = now(), updated_at = now(), lease_token = lease_token + 1, lease_expires_at = NULL WHERE agent IS NOT NULL AND agent NOT IN ({HANDLES},'auto') AND status IN ('queued','running','awaiting_approval')"))


def downgrade():
    # Retired definitions and their history stay retained; do not silently reactivate automations.
    op.execute("UPDATE agent_runs SET status = 'failed' WHERE status IN ('waiting_children','waiting_dependency','blocked','cancelled')")
    op.execute("UPDATE agent_run_events SET kind = 'activity' WHERE kind = 'task'")
    op.drop_constraint(op.f("ck_agent_runs_runstatus"), "agent_runs", type_="check")
    op.create_check_constraint(op.f("ck_agent_runs_runstatus"), "agent_runs", "status IN ('queued','running','awaiting_approval','completed','failed')")
    op.drop_constraint(op.f("ck_agent_run_events_runeventkind"), "agent_run_events", type_="check")
    op.create_check_constraint(op.f("ck_agent_run_events_runeventkind"), "agent_run_events", "kind IN ('step','text','activity','status')")
    op.drop_constraint("fk_coding_runs_origin_run_id_agent_runs", "coding_runs", type_="foreignkey")
    op.drop_column("coding_runs", "origin_run_id")
    op.drop_constraint("fk_agent_runs_parent_run_id_agent_runs", "agent_runs", type_="foreignkey")
    op.drop_constraint("uq_agent_runs_parent_run_id_delegation_key_task_key", "agent_runs", type_="unique")
    op.drop_constraint("uq_agent_runs_outcome_key", "agent_runs", type_="unique")
    op.drop_index("ix_agent_runs_parent_run_id", table_name="agent_runs")
    for name in ("parent_run_id", "delegation_key", "task_key", "depends_on", "task_mutates", "task_result",
                 "waiting_interrupts", "orchestration", "source", "outcome_key", "review_context"):
        op.drop_column("agent_runs", name)
    op.drop_table("agent_preference_versions")
    op.drop_column("agent_preferences", "version")
