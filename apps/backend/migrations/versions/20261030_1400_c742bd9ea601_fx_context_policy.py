"""Pin private fx project context and opt-in project model routing."""
import sqlalchemy as sa
from alembic import op

revision = "c742bd9ea601"
down_revision = "52a9e71bc304"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("automatic_model_routing", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("agent_runtime_bindings", sa.Column("encrypted_context", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("agent_runtime_bindings", "encrypted_context")
    op.drop_column("projects", "automatic_model_routing")
