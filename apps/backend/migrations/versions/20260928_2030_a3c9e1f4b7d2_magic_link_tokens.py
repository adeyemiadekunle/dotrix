"""magic link tokens

Allows "magic_link" as an action token purpose. The purpose column is a VARCHAR with a CHECK
constraint (str_enum), which autogenerate doesn't compare, so this one is written by hand.

Revision ID: a3c9e1f4b7d2
Revises: 6c5da14a4550
Create Date: 2026-09-28 20:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3c9e1f4b7d2"
down_revision: str | None = "6c5da14a4550"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_action_tokens_actiontokenpurpose"  # the full name (op.f: no naming-convention prefix)


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "action_tokens", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), "action_tokens", "purpose IN ('verify_email', 'reset_password', 'magic_link')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM action_tokens WHERE purpose = 'magic_link'")
    op.drop_constraint(op.f(CONSTRAINT), "action_tokens", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "action_tokens", "purpose IN ('verify_email', 'reset_password')")
