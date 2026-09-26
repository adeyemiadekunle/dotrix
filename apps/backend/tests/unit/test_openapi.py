"""Keeps the API docs (and the client generated from them) complete as routes are added."""
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from pmagent_backend.core.settings import Settings
from pmagent_backend.main import create_app


def make_app(**overrides):
    return create_app(
        Settings(
            database_url="postgresql+asyncpg://localhost/unused",
            jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
            log_json=False,
            **overrides,
        )
    )


@pytest.fixture(scope="module")
def spec() -> dict:
    return make_app().openapi()


def operations(spec: dict):
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            yield f"{method.upper()} {path}", op


def test_operation_ids_are_unique_and_readable(spec: dict) -> None:
    ids = Counter(op["operationId"] for _, op in operations(spec))
    assert [i for i, n in ids.items() if n > 1] == []
    # Route function names, not FastAPI's path-derived defaults.
    assert all("_v1_" not in i for i in ids)


def test_every_operation_is_described_and_tagged(spec: dict) -> None:
    undescribed = [name for name, op in operations(spec) if not op.get("description")]
    untagged = [name for name, op in operations(spec) if not op.get("tags")]
    assert undescribed == [] and untagged == []
    declared = {t["name"] for t in spec["tags"]}
    used = {t for _, op in operations(spec) for t in op["tags"]}
    assert used <= declared


def test_errors_are_documented_as_problem_json(spec: dict) -> None:
    for name, op in operations(spec):
        for status, response in op["responses"].items():
            if status.startswith(("4", "5")):
                assert list(response["content"]) == ["application/problem+json"], (name, status)
    assert "ProblemDetail" in spec["components"]["schemas"]
    assert "HTTPValidationError" not in spec["components"]["schemas"]


def test_authenticated_routes_document_401(spec: dict) -> None:
    for name, op in operations(spec):
        if op.get("security"):
            assert "401" in op["responses"], name


# No `with`: the app's startup (database, checkpointer) isn't needed to serve docs.


def test_docs_are_served() -> None:
    client = TestClient(make_app())
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"] == "pmagent API"


def test_docs_can_be_turned_off() -> None:
    client = TestClient(make_app(docs_enabled=False))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
