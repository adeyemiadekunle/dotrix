"""Separate credential saves from rate-limit metadata updates."""
import sqlalchemy as sa
from alembic import op

revision = "e83f5ca92106"
down_revision = "d72e4b9c6105"
branch_labels = depends_on = None


def upgrade():
    op.add_column("user_model_keys", sa.Column("credential_saved_at", sa.DateTime(timezone=True), nullable=True))
    # Old rows have no separate save history; use their latest update conservatively.
    op.execute("UPDATE user_model_keys SET credential_saved_at = updated_at")
    op.alter_column("user_model_keys", "credential_saved_at", nullable=False, server_default=sa.func.now())


def downgrade():
    op.drop_column("user_model_keys", "credential_saved_at")
