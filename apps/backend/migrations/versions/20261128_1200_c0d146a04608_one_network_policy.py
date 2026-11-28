"""One network policy: the workspace's list becomes a limit, each project chooses its own, sessions pin theirs.

Before, a workspace's hosts were added to every project's. To keep what each project's sandboxes reach, each project
in a workspace with hosts now chooses the workspace's and its own, and the workspace has no limit (projects could
already add any host). Runs from before keep reading their project's choice (`network_snapshot` is null).
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c0d146a04608"
down_revision = "c0d146a04607"
branch_labels = None
depends_on = None


def _merged(first: dict | None, second: dict | None) -> dict | None:
    presets: list[str] = []
    hosts: list[str] = []
    for part in (first or {}, second or {}):
        presets += [p for p in part.get("presets") or [] if p not in presets]
        hosts += [h for h in part.get("hosts") or [] if h not in hosts]
    return {"presets": sorted(presets), "hosts": hosts} if presets or hosts else None


def upgrade() -> None:
    op.add_column("coding_runs", sa.Column("network_snapshot", postgresql.JSONB(none_as_null=True), nullable=True))
    bind = op.get_bind()
    workspaces = bind.execute(sa.text(
        "SELECT id, sandbox_network FROM workspaces WHERE sandbox_network IS NOT NULL")).all()
    for workspace_id, shared in workspaces:
        projects = bind.execute(sa.text("SELECT id, sandbox_network FROM projects WHERE workspace_id = :w"),
                                {"w": workspace_id}).all()
        for project_id, own in projects:
            merged = _merged(shared, own)
            bind.execute(sa.text("UPDATE projects SET sandbox_network = CAST(:n AS jsonb) WHERE id = :p"),
                         {"n": json.dumps(merged) if merged else None, "p": project_id})
        bind.execute(sa.text("UPDATE workspaces SET sandbox_network = NULL WHERE id = :w"), {"w": workspace_id})


def downgrade() -> None:
    # Projects keep the hosts they were given. A workspace's limit is dropped: the earlier code would add its hosts to
    # every project's, widening what each may reach.
    op.execute("UPDATE workspaces SET sandbox_network = NULL")
    op.drop_column("coding_runs", "network_snapshot")
