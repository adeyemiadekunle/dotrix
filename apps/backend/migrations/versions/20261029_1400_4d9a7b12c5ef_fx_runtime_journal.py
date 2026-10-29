"""Persist an encrypted per-run runtime journal and checkpoint."""
import sqlalchemy as sa
from alembic import op

revision = "4d9a7b12c5ef"
down_revision = "8b4c7a1e952f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_runtime_journal",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("binding_id", sa.Uuid(), sa.ForeignKey("agent_runtime_bindings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("expected_sequence", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("encrypted", sa.Text(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("binding_id", "sequence"),
        sa.UniqueConstraint("binding_id", "idempotency_key"),
    )
    op.create_index("ix_agent_runtime_journal_workspace_id", "agent_runtime_journal", ["workspace_id"])
    op.create_index("ix_agent_runtime_journal_binding_id", "agent_runtime_journal", ["binding_id"])
    op.create_table(
        "agent_runtime_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("binding_id", sa.Uuid(), sa.ForeignKey("agent_runtime_bindings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("through", sa.BigInteger(), nullable=False),
        sa.Column("encrypted", sa.Text(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("binding_id"),
    )
    op.create_index("ix_agent_runtime_checkpoints_workspace_id", "agent_runtime_checkpoints", ["workspace_id"])
    op.create_table(
        "agent_runtime_delegations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_id", sa.String(200), nullable=False),
        sa.Column("encrypted_batch", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("parent_run_id", "execution_id"),
    )
    op.create_index("ix_agent_runtime_delegations_workspace_id", "agent_runtime_delegations", ["workspace_id"])
    op.create_index("ix_agent_runtime_delegations_parent_run_id", "agent_runtime_delegations", ["parent_run_id"])


def downgrade():
    op.drop_index("ix_agent_runtime_delegations_parent_run_id", table_name="agent_runtime_delegations")
    op.drop_index("ix_agent_runtime_delegations_workspace_id", table_name="agent_runtime_delegations")
    op.drop_table("agent_runtime_delegations")
    op.drop_index("ix_agent_runtime_checkpoints_workspace_id", table_name="agent_runtime_checkpoints")
    op.drop_table("agent_runtime_checkpoints")
    op.drop_index("ix_agent_runtime_journal_binding_id", table_name="agent_runtime_journal")
    op.drop_index("ix_agent_runtime_journal_workspace_id", table_name="agent_runtime_journal")
    op.drop_table("agent_runtime_journal")
