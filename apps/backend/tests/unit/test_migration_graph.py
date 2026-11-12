"""The deployment command `alembic upgrade head` requires one unambiguous head."""
from pathlib import Path

from alembic.script import ScriptDirectory


def test_migrations_have_one_head():
    migrations = Path(__file__).resolve().parents[2] / "migrations"
    heads = ScriptDirectory(str(migrations)).get_heads()
    assert len(heads) == 1, f"Migration histories must be joined before merging: {heads}"
