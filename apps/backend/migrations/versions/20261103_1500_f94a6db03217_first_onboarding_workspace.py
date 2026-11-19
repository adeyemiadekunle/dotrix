"""Remember the first onboarding workspace without converting personal workspaces."""
import sqlalchemy as sa
from alembic import op

revision = "f94a6db03217"
down_revision = "e83f5ca92106"
branch_labels = depends_on = None


def upgrade():
    op.add_column("users", sa.Column("onboarding_workspace_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_users_onboarding_workspace", "users", "workspaces", ["onboarding_workspace_id"], ["id"], ondelete="SET NULL")
    # Existing people already completed account creation; only new accounts see the new first step.
    op.execute("""UPDATE users AS u SET onboarding_workspace_id = (
        SELECT w.id FROM workspaces AS w JOIN memberships AS m ON m.workspace_id = w.id
        WHERE w.created_by_id = u.id AND w.kind = 'personal' AND m.user_id = u.id AND m.role = 'owner'
        ORDER BY w.created_at, w.id LIMIT 1
    )""")


def downgrade():
    op.drop_constraint("fk_users_onboarding_workspace", "users", type_="foreignkey")
    op.drop_column("users", "onboarding_workspace_id")
