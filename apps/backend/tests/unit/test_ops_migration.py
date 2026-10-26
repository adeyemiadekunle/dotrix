"""The historical admin revisions must upgrade existing installations without losing rows."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def rename_migration(monkeypatch):
    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/20261026_1400_e5a9c3b2d716_rename_admin_to_ops.py"
    )
    spec = spec_from_file_location("rename_admin_to_ops", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.op, "get_bind", lambda: None)
    monkeypatch.setattr(module.op, "rename_table", lambda *args: calls.append(("table", args)))
    monkeypatch.setattr(module.op, "alter_column", lambda *args, **kw: calls.append(("column", args, kw)))
    monkeypatch.setattr(module.op, "execute", lambda stmt: calls.append(("sql", str(stmt))))
    return module, calls


def test_old_admin_tables_are_renamed_not_recreated(rename_migration, monkeypatch) -> None:
    migration, calls = rename_migration
    monkeypatch.setattr(
        migration, "inspect", lambda _: SimpleNamespace(get_table_names=lambda: ["admin_users", "admin_sessions"])
    )
    migration.upgrade()
    assert calls[:2] == [("table", ("admin_users", "ops_users")), ("table", ("admin_sessions", "ops_sessions"))]
    assert ("column", ("ops_sessions", "admin_user_id"), {"new_column_name": "ops_user_id", "existing_type": calls[2][2]["existing_type"]}) in calls
    sql = " ".join(call[1] for call in calls if call[0] == "sql")
    assert "fk_admin_sessions_admin_user_id_admin_users TO fk_ops_sessions_ops_user_id_ops_users" in sql
    assert "ix_admin_sessions_admin_user_id RENAME TO ix_ops_sessions_ops_user_id" in sql
    assert "DROP" not in sql


def test_previously_renamed_preview_is_left_alone(rename_migration, monkeypatch) -> None:
    migration, calls = rename_migration
    monkeypatch.setattr(
        migration, "inspect", lambda _: SimpleNamespace(get_table_names=lambda: ["ops_users", "ops_sessions"])
    )
    migration.upgrade()
    assert calls == []


def test_mixed_identity_schema_is_not_silently_modified(rename_migration, monkeypatch) -> None:
    migration, calls = rename_migration
    monkeypatch.setattr(
        migration, "inspect", lambda _: SimpleNamespace(get_table_names=lambda: ["admin_users", "ops_sessions"])
    )
    with pytest.raises(RuntimeError, match="mixed schema"):
        migration.upgrade()
    assert calls == []
