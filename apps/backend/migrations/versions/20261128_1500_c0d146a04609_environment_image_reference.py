"""Room for a full image reference in `coding_runs.environment_image_id`.

OpenShell sandboxes record the operator-approved image as its digest reference
(`registry.example.com/team/coding@sha256:<64 hex>`), longer than the 80 characters the Docker sandbox's
content IDs needed.
"""

import sqlalchemy as sa
from alembic import op

revision = "c0d146a04609"
down_revision = "c0d146a04608"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("coding_runs", "environment_image_id", type_=sa.String(512), existing_type=sa.String(80),
                    existing_nullable=True)


def downgrade() -> None:
    # A reference longer than 80 characters can't go back; keep only what fits (a content ID or a short tag).
    op.execute("UPDATE coding_runs SET environment_image_id = NULL WHERE length(environment_image_id) > 80")
    op.alter_column("coding_runs", "environment_image_id", type_=sa.String(80), existing_type=sa.String(512),
                    existing_nullable=True)
