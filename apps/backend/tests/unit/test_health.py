from datetime import UTC, datetime, timedelta

from httpx import AsyncClient


async def test_liveness(client: AsyncClient) -> None:
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok" and body["version"] == "0.1.0"
    assert body["uptime_seconds"] >= 0
    server_time = datetime.fromisoformat(body["time"])
    assert server_time.utcoffset() == timedelta(0)  # UTC
    assert abs(server_time - datetime.now(UTC)) < timedelta(seconds=5)
    assert res.headers["x-request-id"]
