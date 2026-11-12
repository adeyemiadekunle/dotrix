from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from dotrix_backend.main import API_VERSION


async def test_liveness(client: AsyncClient) -> None:
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    # The version the release script sets (scripts/release.py bump), not a number to edit by hand.
    assert body["status"] == "ok" and body["version"] == API_VERSION
    assert body["uptime_seconds"] >= 0
    server_time = datetime.fromisoformat(body["time"])
    assert server_time.utcoffset() == timedelta(0)  # UTC
    assert abs(server_time - datetime.now(UTC)) < timedelta(seconds=5)
    assert res.headers["x-request-id"]
