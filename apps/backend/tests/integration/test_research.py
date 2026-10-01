"""Research on the platform (docs/agents-v2.md §6.2, §6.3): a run's sources saved with stable
ids, pages cached per workspace, web limits and Tavily credits, and report claims checked
against what was read."""
from collections.abc import Iterator

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.modules.agents.models import AgentRunOutput
from pmagent_backend.modules.research.models import ResearchSource, WebPage
from pmagent_backend.modules.research.service import WebResearch
from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call
from pmagent_engine.web import FakeSearch, PageFetcher, SearchHit

GOV = "https://www.gov.uk/vat-rates"
BLOG = "https://blog.example/vat-tips"
QUOTE = "The standard rate of VAT is 20% on most goods and services."
PAGE = f"<html><head><title>VAT rates</title></head><body><h1>VAT rates</h1><p>{QUOTE}</p><p>{'More detail. ' * 30}</p></body></html>"
HITS = [SearchHit(GOV, "VAT rates", "The standard rate is 20%"), SearchHit(BLOG, "VAT tips", "Rates may change")]


class Tavily(FakeSearch):
    name = "tavily"  # so credits are counted


@pytest.fixture
def site() -> list[str]:
    """The pages the fake web served, by URL."""
    return []


@pytest.fixture
def web(db_client: AsyncClient, site: list[str]) -> Iterator[WebResearch]:
    async def public(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    def serve(request: httpx.Request) -> httpx.Response:
        site.append(str(request.url))
        return httpx.Response(200, content=PAGE.encode(), headers={"content-type": "text/html"})

    research = WebResearch(
        search=Tavily(default=HITS),
        fetcher_factory=lambda: PageFetcher(
            resolver=public, transport=httpx.MockTransport(serve), min_interval=0, respect_robots=False
        ),
    )
    runner = db_client._transport.app.state.runner  # type: ignore[attr-defined]
    runner.web = research
    yield research
    runner.web = None


@pytest.fixture
def world(db_client: AsyncClient, create_team, signup, add_member):
    """Ada owns a team with project KUN; Cat is a member."""

    async def _make():
        ada = await signup()
        cat = await signup(email="cat@example.com", name="Cat")
        team = await create_team(ada.headers)
        await add_member(team["id"], cat.id, Role.MEMBER)
        project = (await db_client.post(f"/v1/workspaces/{team['id']}/projects", json={"key": "KUN", "name": "Kunemi"},
                                        headers=ada.headers)).json()
        return ada, cat, team, f"/v1/workspaces/{team['id']}/projects/{project['id']}"

    return _make


def _report(*claims: tuple[str, str, str]) -> object:
    return tool_call("submit_result", items=[
        {"claim": claim, "sources": [source], "quotes": [{"source": source, "text": text}], "confidence": "high"}
        for claim, source, text in claims
    ])


async def _research(db_client: AsyncClient, base: str, headers: dict, message: str = "What's the UK VAT rate?") -> dict:
    run = (await db_client.post(f"{base}/agent/runs", json={"message": message, "agent": "research"},
                                headers=headers)).json()
    assert run["status"] in ("completed", "awaiting_approval"), run
    return run


async def test_a_research_run_records_its_sources_and_checks_its_claims(
    world, web, site, db_client: AsyncClient, agent_script
) -> None:
    ada, cat, _, base = await world()
    agent_script.say(
        tool_call("web_search", query="uk vat rate"),
        tool_call("fetch_page", url=GOV),
        _report(
            ("VAT is 20%", "S1", QUOTE),
            ("VAT will rise to 25%", "S1", "The standard rate of VAT will rise to 25% next year."),
            ("Rates may change", "S2", "Rates may change"),
        ),
        "VAT is 20% [S1].",
    )
    run = await _research(db_client, base, ada.headers)
    assert run["reply"] == "VAT is 20% [S1]." and site == [GOV]

    sources = {s["label"]: s for s in run["sources"]}
    assert list(sources) == ["S1", "S2"]
    assert sources["S1"] | {"fetched_at": None} == {
        "label": "S1", "url": GOV, "title": "VAT rates", "host": "gov.uk", "tier": "primary", "kind": "page",
        "published": None, "fetched_at": None, "flagged": [],
    }
    assert sources["S1"]["fetched_at"] and sources["S2"]["kind"] == "search" and sources["S2"]["tier"] == "other"

    [output] = run["outputs"]
    assert output["kind"] == "report"
    checks = [item["check"] for item in output["items"]]
    assert checks == [
        {"status": "supported", "quotes": [{"source": "S1", "found": "page"}]},
        {"status": "unsupported", "quotes": [{"source": "S1", "found": None}]},
        {"status": "weak", "quotes": [{"source": "S2", "found": "snippet"}]},
    ]
    assert run["breakdown"]["web"] == {"searches": 1, "fetches": 1, "credits": 1, "flagged": []}

    # Members see the sources and checks; usage stays for owners and admins.
    seen = (await db_client.get(f"{base}/agent/runs/{run['id']}", headers=cat.headers)).json()
    assert [s["label"] for s in seen["sources"]] == ["S1", "S2"] and seen["breakdown"] is None
    assert seen["outputs"][0]["items"][0]["check"]["status"] == "supported"


async def test_source_ids_stay_the_same_when_a_run_resumes(world, web, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, base = await world()
    agent_script.say(
        tool_call("web_search", query="uk vat rate"),
        tool_call("write_file", file_path="/pmagent/research/vat.md", content="# VAT\n\n20% [S1]\n"),
        tool_call("fetch_page", url=BLOG),
        "Saved; the blog [S2] agrees.",
    )
    run = await _research(db_client, base, ada.headers)
    assert run["status"] == "awaiting_approval"
    [approval] = run["approvals"]
    done = (await db_client.post(
        f"{base}/agent/runs/{run['id']}/decisions",
        json={"decisions": [{"approval_id": approval["id"], "decision": "approve"}]}, headers=ada.headers,
    )).json()
    assert done["status"] == "completed", done
    assert [(s["label"], s["url"], s["kind"]) for s in done["sources"]] == [("S1", GOV, "search"), ("S2", BLOG, "page")]
    # Usage covers both steps.
    assert done["breakdown"]["web"]["searches"] == 1 and done["breakdown"]["web"]["fetches"] == 1


async def test_pages_are_cached_per_workspace(
    world, web, site, db_client: AsyncClient, agent_script, signup, create_team, db_session: AsyncSession
) -> None:
    ada, _, team, base = await world()
    for _ in range(2):
        agent_script.say(tool_call("fetch_page", url=GOV), "Read it.")
        await _research(db_client, base, ada.headers)
    assert site == [GOV]  # the second run read it from the workspace's cache

    eve = await signup(email="eve@example.com", name="Eve")
    other = await create_team(eve.headers, "Other")
    project = (await db_client.post(f"/v1/workspaces/{other['id']}/projects", json={"key": "OTH", "name": "Other"},
                                    headers=eve.headers)).json()
    agent_script.say(tool_call("fetch_page", url=GOV), "Read it.")
    await _research(db_client, f"/v1/workspaces/{other['id']}/projects/{project['id']}", eve.headers)
    assert site == [GOV, GOV]  # never served from another workspace's cache
    owners = set(await db_session.scalars(select(WebPage.workspace_id)))
    assert {str(w) for w in owners} == {team["id"], other["id"]}


async def test_tavily_credits_are_capped_per_workspace_per_day(
    world, web: WebResearch, db_client: AsyncClient, agent_script
) -> None:
    ada, _, _, base = await world()
    web.daily_credits = 1
    agent_script.say(tool_call("web_search", query="uk vat rate"), "Found it.")
    first = await _research(db_client, base, ada.headers)
    assert first["breakdown"]["web"]["credits"] == 1

    model = agent_script.say(tool_call("web_search", query="uk vat rate"), "Out of searches.")
    second = await _research(db_client, base, ada.headers)
    assert second["breakdown"]["web"] == {"searches": 0, "fetches": 0, "credits": 0, "flagged": []}
    assert "allowance is used up" in str(model.received[-1][-1].content)


async def test_searches_per_run_are_limited(world, web: WebResearch, db_client: AsyncClient, agent_script) -> None:
    ada, _, _, base = await world()
    web.max_searches = 1
    model = agent_script.say(tool_call("web_search", query="one"), tool_call("web_search", query="two"), "Done.")
    run = await _research(db_client, base, ada.headers)
    assert run["breakdown"]["web"]["searches"] == 1
    assert "searches are used up" in str(model.received[-1][-1].content)


async def test_research_moves_with_its_project(
    world, web, db_client: AsyncClient, agent_script, create_team, db_session: AsyncSession
) -> None:
    ada, _, _, base = await world()
    agent_script.say(tool_call("web_search", query="vat"), _report(("VAT is 20%", "S1", QUOTE)), "Done.")
    await _research(db_client, base, ada.headers)
    acme = await create_team(ada.headers, "Acme")
    moved = await db_client.post(f"{base}/move", json={"workspace_id": acme["id"]}, headers=ada.headers)
    assert moved.status_code == 200, moved.text
    for model in (ResearchSource, AgentRunOutput):
        assert {str(w) for w in await db_session.scalars(select(model.workspace_id))} == {acme["id"]}
