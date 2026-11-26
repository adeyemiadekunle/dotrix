"""Aggregate website traffic and public release downloads for the admin console."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic

import httpx

from dotrix_backend.core.settings import Settings

from .schemas import GrowthSnapshot, ReleaseDownloads, WebsiteTraffic

_CLOUDFLARE_URL = "https://api.cloudflare.com/client/v4/graphql"
_GITHUB_RELEASES = "https://api.github.com/repos/adeyemiadekunle/dotrix/releases"
_CACHE_SECONDS = 300
_QUERY = """
query WebsiteTraffic($account: String!, $site: String!, $start: Time!, $end: Time!) {
  viewer {
    accounts(filter: {accountTag: $account}) {
      rumPageloadEventsAdaptiveGroups(
        limit: 1
        filter: {siteTag: $site, datetime_geq: $start, datetime_lt: $end}
      ) {
        count
        sum { visits }
      }
    }
  }
}
"""


async def _traffic(client: httpx.AsyncClient, settings: Settings) -> WebsiteTraffic:
    account = settings.cloudflare_analytics_account_id
    site = settings.cloudflare_analytics_site_tag
    token = settings.cloudflare_analytics_api_token
    if not (account and site and token):
        return WebsiteTraffic(status="unconfigured")

    now = datetime.now(UTC).replace(microsecond=0)
    variables = {
        "account": account, "site": site,
        "start": (now - timedelta(days=7)).isoformat(), "end": now.isoformat(),
    }
    try:
        async with asyncio.timeout(8):
            response = await client.post(
                _CLOUDFLARE_URL, json={"query": _QUERY, "variables": variables},
                headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("errors"):
                return WebsiteTraffic(status="unavailable")
            accounts = data["data"]["viewer"]["accounts"]
            totals = accounts[0]["rumPageloadEventsAdaptiveGroups"]
            if not totals:
                return WebsiteTraffic(status="ready", page_views=0, visits=0)
            return WebsiteTraffic(
                status="ready", page_views=totals[0]["count"], visits=totals[0]["sum"]["visits"],
            )
    except (httpx.HTTPError, TimeoutError, KeyError, IndexError, TypeError, ValueError):
        return WebsiteTraffic(status="unavailable")


async def _downloads(client: httpx.AsyncClient) -> ReleaseDownloads:
    desktop = cli = 0
    try:
        async with asyncio.timeout(8):
            for page in range(1, 11):
                response = await client.get(
                    _GITHUB_RELEASES,
                    params={"page": page, "per_page": 100},
                    headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                )
                response.raise_for_status()
                releases = response.json()
                if not isinstance(releases, list):
                    return ReleaseDownloads(status="unavailable")
                for release in releases:
                    if release["draft"] or release["prerelease"]:
                        continue
                    for asset in release["assets"]:
                        name = asset["name"]
                        if name.startswith("dotrix-cli-") and name.endswith(".zip"):
                            cli += asset["download_count"]
                        elif name.startswith("dotrix-") and name.endswith("-setup.exe"):
                            desktop += asset["download_count"]
                if "next" not in response.links:
                    return ReleaseDownloads(status="ready", desktop=desktop, cli=cli)
    except (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError):
        pass
    return ReleaseDownloads(status="unavailable")


class GrowthMetrics:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport
        self._snapshot: GrowthSnapshot | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def snapshot(self) -> GrowthSnapshot:
        async with self._lock:
            if self._snapshot is not None and monotonic() < self._expires:
                return self._snapshot
            async with httpx.AsyncClient(timeout=5, transport=self._transport) as client:
                traffic, downloads = await asyncio.gather(_traffic(client, self._settings), _downloads(client))
            self._snapshot = GrowthSnapshot(traffic=traffic, downloads=downloads)
            self._expires = monotonic() + _CACHE_SECONDS
            return self._snapshot
