from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from dotrix_backend.core.errors import NotFound
from dotrix_backend.core.settings import Settings
from dotrix_backend.main import create_app

router = APIRouter()


class Payload(BaseModel):
    name: str


@router.get("/boom/not-found")
async def not_found() -> None:
    raise NotFound("Issue KUN-9 not found")


@router.get("/boom/crash")
async def crash() -> None:
    raise RuntimeError("secret internal detail")


@router.post("/boom/validate")
async def validate(payload: Payload) -> Payload:
    return payload


def make_client() -> AsyncClient:
    app = create_app(
        Settings(
            env="test",
            log_json=False,
            database_url="postgresql+asyncpg://localhost/unused",
            jwt_secret="test-only-jwt-secret-not-used-anywhere-else",  # type: ignore[arg-type]
        )
    )
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_domain_error_maps_to_problem_json() -> None:
    async with make_client() as client:
        res = await client.get("/boom/not-found", headers={"X-Request-ID": "req-123"})
    assert res.status_code == 404
    assert res.headers["content-type"] == "application/problem+json"
    body = res.json()
    assert body["detail"] == "Issue KUN-9 not found"
    assert body["request_id"] == "req-123"
    assert res.headers["x-request-id"] == "req-123"


async def test_unhandled_error_is_500_without_leaking_details() -> None:
    async with make_client() as client:
        res = await client.get("/boom/crash")
    assert res.status_code == 500
    body = res.json()
    assert "secret" not in res.text
    assert body["request_id"] == res.headers["x-request-id"]


async def test_validation_error_lists_fields() -> None:
    async with make_client() as client:
        res = await client.post("/boom/validate", json={})
    assert res.status_code == 422
    assert res.json()["errors"][0]["loc"] == ["body", "name"]


async def test_unknown_route_is_problem_json() -> None:
    async with make_client() as client:
        res = await client.get("/nope")
    assert res.status_code == 404
    assert res.headers["content-type"] == "application/problem+json"
