"""The aggregation contract for the admin console's external growth metrics."""
import asyncio
import json
from datetime import datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from dotrix_backend.core.settings import Settings
from dotrix_backend.modules.admin.growth import GrowthMetrics


def release(*assets: tuple[str, int], prerelease: bool = False) -> dict:
    return {
        "draft": False,
        "prerelease": prerelease,
        "assets": [{"name": name, "download_count": count} for name, count in assets],
    }


async def test_growth_uses_separate_sources_and_caches_concurrent_reads() -> None:
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host == "api.cloudflare.com":
            assert request.headers["Authorization"] == "Bearer private-token"
            variables = json.loads(request.content)["variables"]
            assert (variables["account"], variables["site"]) == ("account", "site")
            assert datetime.fromisoformat(variables["end"]) - datetime.fromisoformat(variables["start"]) == timedelta(days=7)
            return httpx.Response(200, json={"data": {"viewer": {"accounts": [
                {"rumPageloadEventsAdaptiveGroups": [{"count": 32, "sum": {"visits": 21}}]},
            ]}}})
        assert request.url.host == "api.github.com" and "Authorization" not in request.headers
        if request.url.params.get("page") == "1":
            return httpx.Response(200, headers={"Link": '<https://api.github.com/releases?page=2>; rel="next"'}, json=[
                release(("dotrix-0.4.0-windows-x64-setup.exe", 9), ("latest.yml", 60)),
                release(("dotrix-cli-0.5.0-windows-x64.zip", 73), prerelease=True),
            ])
        return httpx.Response(200, json=[release(("dotrix-cli-0.4.0-windows-x64.zip", 8))])

    settings = Settings(
        database_url="postgresql+psycopg://localhost/unused",
        jwt_secret=SecretStr("test-signing-secret" * 3),
        cloudflare_analytics_account_id="account",
        cloudflare_analytics_site_tag="site",
        cloudflare_analytics_api_token=SecretStr("private-token"),
    )
    metrics = GrowthMetrics(settings, transport=httpx.MockTransport(respond))
    first, second = await asyncio.gather(metrics.snapshot(), metrics.snapshot())
    assert first is second
    assert first.model_dump() == {
        "traffic": {"status": "ready", "page_views": 32, "visits": 21},
        "downloads": {"status": "ready", "desktop": 9, "cli": 8},
    }
    assert sorted(seen) == ["api.cloudflare.com", "api.github.com", "api.github.com"]


@pytest.mark.parametrize(("configured", "status"), [(False, "unconfigured"), (True, "unavailable")])
async def test_traffic_configuration_and_errors_do_not_hide_downloads(configured: bool, status: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.cloudflare.com":
            assert configured
            return httpx.Response(200, json={"errors": [{"message": "denied"}]})
        return httpx.Response(200, json=[])

    settings = Settings(
        database_url="postgresql+psycopg://localhost/unused",
        jwt_secret=SecretStr("test-signing-secret" * 3),
        cloudflare_analytics_account_id="account" if configured else None,
        cloudflare_analytics_site_tag="site",
        cloudflare_analytics_api_token=SecretStr("private-token"),
    )
    snapshot = await GrowthMetrics(settings, transport=httpx.MockTransport(respond)).snapshot()
    assert snapshot.traffic.status == status and snapshot.traffic.visits is None
    assert snapshot.downloads.status == "ready" and snapshot.downloads.cli == 0
