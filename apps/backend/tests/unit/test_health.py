from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert res.headers["x-request-id"]
