"""Hybrid search over a project's documents and issues (full text + pgvector)."""
import hashlib
import math
import re

import pytest
from httpx import AsyncClient

from pmagent_backend.core.jobs import JobContext
from pmagent_backend.jobs import index_knowledge
from pmagent_backend.modules.search.models import EMBEDDING_DIMENSIONS
from pmagent_backend.modules.workspaces.models import Role
from pmagent_engine.testing import tool_call

# The fake embedder knows a few synonyms, so a paraphrase lands near the original, as with a
# real embedding model; keyword search alone can't find those.
SYNONYMS = {"courier": "driver", "couriers": "driver", "drivers": "driver", "payouts": "payment",
            "payout": "payment", "payments": "payment", "paid": "payment"}


class FakeEmbedder:
    model = "fake:bag-of-words"
    min_similarity = 0.1  # any shared word

    def __init__(self) -> None:
        self.documents_embedded = 0
        self.queries = 0

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for word in re.findall(r"[a-z]+", text.lower()):
            word = SYNONYMS.get(word, word)
            if len(word) < 4:
                continue
            vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % EMBEDDING_DIMENSIONS] += 1
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents_embedded += len(texts)
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries += 1
        return self._vector(text)


PAYMENTS = """# Finance

## Driver payments
Each driver is paid weekly for the parcels they deliver, by bank transfer.

## Invoicing
Business customers get a monthly invoice with every shipment listed.
"""

HUBS = """# Hubs

## Lagos
The Ikeja hub sorts parcels for Lagos and Ogun.

## Abuja
The Wuse hub serves the capital; its forklift error E-417 recurs on Mondays.
"""


@pytest.fixture
def embedder(db_client: AsyncClient) -> FakeEmbedder:
    fake = FakeEmbedder()
    app = db_client._transport.app  # type: ignore[attr-defined]
    app.state.embedder = fake
    app.state.runner.embedder = fake
    return fake


@pytest.fixture
def project(db_client: AsyncClient, create_team, signup):
    async def _make(email: str = "ada@example.com", key: str = "KUN"):
        person = await signup(email=email)
        team = await create_team(person.headers)
        created = (
            await db_client.post(
                f"/v1/workspaces/{team['id']}/projects", json={"key": key, "name": "Kunemi"}, headers=person.headers
            )
        ).json()
        base = f"/v1/workspaces/{team['id']}/projects/{created['id']}"
        for path, content in (("finance.md", PAYMENTS), ("hubs.md", HUBS)):
            res = await db_client.put(f"{base}/knowledge/files/{path}", json={"content": content}, headers=person.headers)
            assert res.status_code in (200, 201), res.text
        return person, team, base, created

    return _make


async def search(client: AsyncClient, base: str, headers, q: str, **params) -> list[dict]:
    res = await client.get(f"{base}/search", params={"q": q, **params}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def index(db_client: AsyncClient, embedder: FakeEmbedder) -> int:
    app = db_client._transport.app  # type: ignore[attr-defined]
    ctx = app.state.jobs.ctx
    return await index_knowledge(JobContext(ctx.session_factory, ctx.settings, ctx.email, ctx.storage, embedder))


async def test_keywords_find_sections_and_issues(db_client: AsyncClient, project) -> None:
    ada, _, base, _ = await project()
    issue = (
        await db_client.post(
            f"{base}/issues",
            json={"type": "bug", "title": "Forklift keeps failing", "description": "Error E-417 at the Wuse hub."},
            headers=ada.headers,
        )
    ).json()
    hits = await search(db_client, base, ada.headers, "E-417")
    assert [(h["source"], h["ref"]) for h in hits][:2] in (
        [("document", "hubs.md"), ("issue", issue["key"])],
        [("issue", issue["key"]), ("document", "hubs.md")],
    )
    section = next(h for h in hits if h["source"] == "document")
    assert section["heading"] == "Hubs > Abuja" and "Wuse hub" in section["snippet"]
    assert section["version"] == 1
    # By issue key, and only issues.
    by_key = await search(db_client, base, ada.headers, issue["key"], source="issue")
    assert by_key[0]["ref"] == issue["key"] and by_key[0]["heading"] == "Forklift keeps failing"
    # Agent rules are instructions, not project knowledge.
    assert all(not h["ref"].startswith("agent-rules/") for h in await search(db_client, base, ada.headers, "agent"))


async def test_paraphrases_match_with_embeddings(db_client: AsyncClient, project, embedder) -> None:
    ada, _, base, _ = await project()
    assert await search(db_client, base, ada.headers, "courier payouts", source="document") == []  # no shared words
    assert await index(db_client, embedder) > 0  # the background job adds the vectors
    hits = await search(db_client, base, ada.headers, "courier payouts", source="document")
    assert hits and hits[0]["ref"] == "finance.md" and hits[0]["heading"] == "Finance > Driver payments"
    assert embedder.queries == 2


async def test_only_changed_text_is_embedded_again(db_client: AsyncClient, project, embedder) -> None:
    ada, _, base, _ = await project()
    await index(db_client, embedder)
    first = embedder.documents_embedded
    assert await index(db_client, embedder) == 0  # nothing changed, nothing to do
    edited = HUBS.replace("sorts parcels for Lagos and Ogun", "sorts parcels for Lagos, Ogun, and Oyo")
    await db_client.put(f"{base}/knowledge/files/hubs.md", json={"content": edited}, headers=ada.headers)
    assert await index(db_client, embedder) == 1  # only the changed section is embedded again
    assert embedder.documents_embedded == first + 1
    hits = await search(db_client, base, ada.headers, "Oyo")
    assert hits[0]["ref"] == "hubs.md" and hits[0]["version"] == 2


async def test_deleted_documents_leave_the_index(db_client: AsyncClient, project) -> None:
    ada, _, base, _ = await project()
    assert await search(db_client, base, ada.headers, "Wuse")
    res = await db_client.delete(f"{base}/knowledge/files/hubs.md", headers=ada.headers)
    assert res.status_code in (200, 204), res.text
    assert await search(db_client, base, ada.headers, "Wuse") == []


async def test_issue_changes_and_comments_are_searchable(db_client: AsyncClient, project) -> None:
    ada, _, base, _ = await project()
    issue = (
        await db_client.post(f"{base}/issues", json={"type": "task", "title": "Set up the Kano hub"}, headers=ada.headers)
    ).json()
    assert await search(db_client, base, ada.headers, "generator") == []
    await db_client.post(
        f"{base}/issues/{issue['key']}/comments", json={"body": "Needs a backup generator first."}, headers=ada.headers
    )
    hits = await search(db_client, base, ada.headers, "generator")
    assert [h["ref"] for h in hits] == [issue["key"]] and "backup generator" in hits[0]["snippet"]


async def test_search_stays_in_its_project(db_client: AsyncClient, project, embedder, signup, add_member) -> None:
    ada, team, base, _ = await project()
    bea, _, other_base, _ = await project(email="bea@example.com", key="OTH")
    await db_client.put(
        f"{other_base}/knowledge/files/secret.md", json={"content": "# Secret\n\nThe Zamfara expansion plan."},
        headers=bea.headers,
    )
    await index(db_client, embedder)
    assert await search(db_client, base, ada.headers, "Zamfara expansion") == []
    # Vector search is scoped too: the nearest chunks elsewhere never show up.
    assert all(h["ref"] != "secret.md" for h in await search(db_client, base, ada.headers, "expansion plan"))
    # Another workspace's project is not found at all.
    assert (await db_client.get(f"{other_base}/search", params={"q": "x"}, headers=ada.headers)).status_code == 404
    # Members (and guests who can see the project) may search.
    cy = await signup(email="cy@example.com", name="Cy")
    await add_member(team["id"], cy.id, Role.MEMBER)
    assert await search(db_client, base, cy.headers, "Wuse")


async def test_agents_search_and_read_sections(db_client: AsyncClient, project, agent_script, embedder) -> None:
    ada, _, base, _ = await project()
    model = agent_script.say(
        tool_call("search_knowledge", call_id="s", query="forklift error"),
        tool_call("document_outline", call_id="o", file_path="/pmagent/hubs.md"),
        tool_call("read_section", call_id="r", file_path="/pmagent/hubs.md", heading="Abuja"),
        "The Wuse hub's forklift fails on Mondays (E-417).",
    )
    res = await db_client.post(f"{base}/agent/runs", json={"message": "What's wrong at Abuja?"}, headers=ada.headers)
    done = res.json()
    assert done["status"] == "completed", done
    results = [m.content for m in model.received[3] if m.type == "tool"]
    found, outline, section = results
    assert "/pmagent/hubs.md v1, Hubs > Abuja" in found and "E-417" in found
    assert "## Lagos (lines 3-5" in outline and "## Abuja (lines 6-" in outline
    assert section.startswith("/pmagent/hubs.md v1, ## Abuja") and "E-417" in section and "Ikeja" not in section
    files = {f["path"] for f in done["breakdown"]["files_read"]}
    assert files == {"/pmagent/hubs.md"}  # outline and section reads count as reads
    # The prompt tells agents about these tools.
    assert "search_knowledge(query)" in str(model.received[0][0].content)


async def test_missing_sections_list_what_exists(db_client: AsyncClient, project, agent_script) -> None:
    ada, _, base, _ = await project()
    model = agent_script.say(
        tool_call("read_section", call_id="r", file_path="/pmagent/hubs.md", heading="Kano"),
        tool_call("document_outline", call_id="o", file_path="/pmagent/nope.md"),
        "ok",
    )
    await db_client.post(f"{base}/agent/runs", json={"message": "Kano?"}, headers=ada.headers)
    missing, gone = [m.content for m in model.received[2] if m.type == "tool"]
    assert "No section 'Kano' in /pmagent/hubs.md" in missing and "## Abuja" in missing
    assert "not found" in gone


async def test_near_duplicate_issues_match_without_embeddings(db_client: AsyncClient, project) -> None:
    ada, _, base, _ = await project()
    for title in ("Add dark mode to the dispatch screen", "Add CSV export for invoices"):
        await db_client.post(f"{base}/issues", json={"type": "task", "title": title}, headers=ada.headers)
    hits = await search(db_client, base, ada.headers, "Add a dark mode toggle", source="issue", limit=3)
    assert [h["heading"] for h in hits] == ["Add dark mode to the dispatch screen"]  # most words, not just "add"
    assert await search(db_client, base, ada.headers, "Add payment reminders", source="issue") == []


async def test_search_across_the_workspace(signup, create_team, add_member, db_client: AsyncClient) -> None:
    ada = await signup()
    bob = await signup(email="bob@example.com", name="Bob")
    team = await create_team(ada.headers)
    await add_member(team["id"], bob.id, Role.MEMBER)
    ws = f"/v1/workspaces/{team['id']}"
    projects = {}
    for key in ("KUN", "MOB"):
        res = await db_client.post(f"{ws}/projects", json={"key": key, "name": key.title()}, headers=ada.headers)
        projects[key] = res.json()
    for key, title in (("KUN", "Driver payouts every week"), ("MOB", "Driver onboarding in the app")):
        res = await db_client.post(
            f"{ws}/projects/{projects[key]['id']}/issues", json={"title": title}, headers=ada.headers
        )
        assert res.status_code == 201, res.text

    hits = (await db_client.get(f"{ws}/search", params={"q": "driver", "source": "issue"}, headers=ada.headers)).json()
    assert sorted((h["project_key"], h["ref"]) for h in hits) == [("KUN", "KUN-1"), ("MOB", "MOB-1")]

    # Restricted projects you aren't on are left out.
    await db_client.patch(f"{ws}/projects/{projects['MOB']['id']}", json={"access": "restricted"}, headers=ada.headers)
    seen = (await db_client.get(f"{ws}/search", params={"q": "driver", "source": "issue"}, headers=bob.headers)).json()
    assert [h["project_key"] for h in seen] == ["KUN"]
