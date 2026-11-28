"""Host secrets (coding/secrets.py): write-only, encrypted, audited without values, pinned per session, and handed only
to a sandbox that keeps them out, for hosts the turn's network policy allows."""
import dataclasses
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

from apps.backend.tests.integration.test_coding import (  # noqa: F401  (fixtures)
    ScriptedClaude,
    _approve,
    checkout,
    claude,
    coding,
    origin,
)
from apps.backend.tests.integration.test_sandbox_network import SleepingSandbox
from dotrix_backend.modules.audit.models import AuditEvent
from dotrix_backend.modules.coding.models import CodingRun, CodingSecret
from dotrix_backend.modules.coding.warm import WarmPool

VALUE = "npm_REAL-secret-value-1234"


class SecretSandbox(SleepingSandbox):
    """Records the secrets each sandbox was opened with, as Docker Cloud and OpenShell would take them."""

    def __init__(self, agent) -> None:
        super().__init__(agent)
        self.secrets: list[list] = []

    async def open(self, run_id, source, tool, model_key, *, allow=(), secrets=()):
        self.secrets.append(list(secrets))
        return await super().open(run_id, source, tool, model_key, allow=allow)


async def test_secrets_are_write_only_encrypted_audited_and_limited_to_the_network_policy(
    db_client: AsyncClient, coding, db_session,  # noqa: F811
) -> None:
    ada, cat, ws, kun, mob, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    url = f"{base}/coding/secrets/NPM_TOKEN"
    body = {"host": "registry.npmjs.org", "value": VALUE}

    # Its host must be in the project's network policy first.
    refused = await db_client.put(url, json=body, headers=ada.headers)
    assert refused.status_code == 409 and "network policy" in refused.text
    await db_client.put(f"{base}/coding/network", json={"presets": ["npm"], "hosts": ["*.example.com"]},
                        headers=ada.headers)
    assert (await db_client.put(url, json=body, headers=cat.headers)).status_code == 403
    assert (await db_client.get(f"{base}/coding/secrets", headers=cat.headers)).status_code == 403
    assert (await db_client.put(url, json={"host": "*.example.com", "value": VALUE},
                                headers=ada.headers)).status_code == 422  # one host, not a wildcard
    assert (await db_client.put(url, json={"host": "registry.npmjs.org", "header": "Host", "value": VALUE},
                                headers=ada.headers)).status_code == 422
    assert (await db_client.put(f"{base}/coding/secrets/GITHUB_TOKEN", json=body,
                                headers=ada.headers)).status_code == 409  # a name the sandbox or tools use
    assert (await db_client.put(url, json={"host": "registry.npmjs.org"},
                                headers=ada.headers)).status_code == 409  # a new one needs its value

    saved = await db_client.put(url, json=body, headers=ada.headers)
    assert saved.status_code == 200, saved.text
    read = saved.json()
    assert read["name"] == "NPM_TOKEN" and read["header"] == "Authorization" and read["prefix"] == "Bearer "
    assert read["allowed"] and read["version"] == 1 and "value" not in read
    # A host a wildcard allows is fine, named exactly.
    assert (await db_client.put(f"{base}/coding/secrets/TEST_API", json={
        "host": "api.example.com", "header": "X-Api-Key", "prefix": "", "value": "k"}, headers=ada.headers)).status_code == 200
    listed = (await db_client.get(f"{base}/coding/secrets", headers=ada.headers)).json()
    assert [s["name"] for s in listed] == ["NPM_TOKEN", "TEST_API"] and VALUE not in str(listed)
    assert (await db_client.get(f"{ws}/projects/{mob['id']}/coding/secrets", headers=ada.headers)).json() == []

    row = await db_session.scalar(select(CodingSecret).where(CodingSecret.name == "NPM_TOKEN"))
    assert VALUE not in row.encrypted
    # Changing the rest keeps the value; the version moves either way.
    kept = (await db_client.put(url, json={"host": "registry.npmjs.org", "prefix": "Token "},
                                headers=ada.headers)).json()
    assert kept["version"] == 2 and kept["prefix"] == "Token "
    await db_session.refresh(row)
    app = db_client._transport.app  # type: ignore[attr-defined]
    assert app.state.secrets.decrypt(row.encrypted) == VALUE

    # Variables and secrets can't share a name, either way round.
    clash = await db_client.put(f"{base}/coding/environment", headers=ada.headers,
                                json={"revision": 0, "enabled": True, "variables": {"NPM_TOKEN": "x"}})
    assert clash.status_code in (409, 422)
    await db_client.put(f"{base}/coding/environment", headers=ada.headers,
                        json={"revision": 0, "enabled": True, "variables": {"REGISTRY_USER": "ci"}})
    assert (await db_client.put(f"{base}/coding/secrets/REGISTRY_USER", json=body,
                                headers=ada.headers)).status_code == 409

    # Leaving the network policy: still listed, no longer allowed.
    await db_client.put(f"{base}/coding/network", json={"presets": ["npm"]}, headers=ada.headers)
    listed = {s["name"]: s for s in (await db_client.get(f"{base}/coding/secrets", headers=ada.headers)).json()}
    assert listed["NPM_TOKEN"]["allowed"] and not listed["TEST_API"]["allowed"]

    assert (await db_client.delete(f"{base}/coding/secrets/TEST_API", headers=ada.headers)).status_code == 204
    assert (await db_client.delete(f"{base}/coding/secrets/TEST_API", headers=ada.headers)).status_code == 404

    audited = list(await db_session.scalars(select(AuditEvent).where(AuditEvent.action.like("coding_secret.%"))
                                            .order_by(AuditEvent.created_at)))
    assert [a.action for a in audited] == ["coding_secret.created", "coding_secret.created", "coding_secret.updated",
                                           "coding_secret.deleted"]
    assert all(VALUE not in str(a.details) and "k" != a.details.get("value") for a in audited)
    assert audited[2].details["value_changed"] is False


async def test_a_session_pins_its_secrets_and_each_turn_sends_their_values_as_they_are(
    db_client: AsyncClient, coding, github, origin: Path, claude: ScriptedClaude, agent_script, db_session, storage,  # noqa: F811
) -> None:
    ada, _, ws, kun, _, _ = coding
    app = db_client._transport.app  # type: ignore[attr-defined]
    jobs = app.state.jobs
    sandbox = SecretSandbox(claude)
    worker = dataclasses.replace(jobs.ctx.coding, sandbox=sandbox, storage=storage, secrets=app.state.secrets,
                                 pool=WarmPool(3600, 0))
    jobs.ctx = dataclasses.replace(jobs.ctx, coding=worker)
    claude.found_transcript, claude.argvs = [], []
    base = f"{ws}/projects/{kun['id']}"
    agent_script.say("Fine.", "Fine again.", "And again.")
    await db_client.put(f"{base}/coding/network", json={"presets": ["npm"]}, headers=ada.headers)
    await db_client.put(f"{base}/coding/secrets/NPM_TOKEN", json={"host": "registry.npmjs.org", "value": VALUE},
                        headers=ada.headers)
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()

    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    asked = (await db_client.post(f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json()
    # The brief names the variable and how to send it, never the value.
    assert "`NPM_TOKEN` for registry.npmjs.org" in asked["brief"] and VALUE not in asked["brief"]
    first = await _approve(db_client, base, asked, ada.headers)
    assert first["status"] == "pr_opened", first
    [[secret]] = sandbox.secrets
    assert (secret.name, secret.host, secret.port, secret.header, secret.prefix, secret.value) == (
        "NPM_TOKEN", "registry.npmjs.org", 443, "Authorization", "Bearer ", VALUE)
    assert VALUE not in repr(secret)
    stored = await db_session.get(CodingRun, first["id"])
    assert stored.secret_snapshot == [{"name": "NPM_TOKEN", "host": "registry.npmjs.org", "header": "Authorization",
                                       "prefix": "Bearer "}]

    # A rotated value reaches the session's next turn, in a new sandbox (the asleep one had the old version);
    # a secret added since is for new sessions.
    await db_client.put(f"{base}/coding/secrets/NPM_TOKEN", json={"host": "registry.npmjs.org", "value": "rotated"},
                        headers=ada.headers)
    await db_client.put(f"{base}/coding/network", json={"presets": ["npm", "pypi"]}, headers=ada.headers)
    await db_client.put(f"{base}/coding/secrets/PYPI_TOKEN", json={"host": "pypi.org", "value": "p"}, headers=ada.headers)
    turns = f"{base}/coding/sessions/{first['session_id']}/turns"
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0\n    return amount\n"}
    second = await _approve(db_client, base, (await db_client.post(
        turns, json={"message": "Only positive"}, headers=ada.headers)).json(), ada.headers)
    assert second["status"] == "pr_opened", second
    assert sandbox.woken == 0 and sandbox.opened == 2
    assert [(s.name, s.value) for s in sandbox.secrets[-1]] == [("NPM_TOKEN", "rotated")]

    # Moved to another host: left out, and the turn says so.
    await db_client.put(f"{base}/coding/network", json={"presets": ["npm"], "hosts": ["npm.example.com"]},
                        headers=ada.headers)
    await db_client.put(f"{base}/coding/secrets/NPM_TOKEN", json={"host": "npm.example.com"}, headers=ada.headers)
    claude.edits = {"src/refunds.py": "def refund(amount):\n    assert amount > 0, 'positive'\n    return amount\n"}
    third = await _approve(db_client, base, (await db_client.post(
        turns, json={"message": "Say why"}, headers=ada.headers)).json(), ada.headers)
    assert third["status"] == "pr_opened", third
    assert sandbox.secrets[-1] == []
    assert any("Host secret left out: NPM_TOKEN now goes to another host" in e["text"] for e in third["events"]), \
        [e["text"] for e in third["events"]]


async def test_the_local_sandbox_refuses_a_turn_with_secrets(
    db_client: AsyncClient, coding, github, claude: ScriptedClaude, agent_script,  # noqa: F811
) -> None:
    ada, _, ws, kun, _, _ = coding
    base = f"{ws}/projects/{kun['id']}"
    agent_script.say("Fine.")
    await db_client.put(f"{base}/coding/network", json={"presets": ["npm"]}, headers=ada.headers)
    await db_client.put(f"{base}/coding/secrets/NPM_TOKEN", json={"host": "registry.npmjs.org", "value": VALUE},
                        headers=ada.headers)
    task = (await db_client.post(f"{base}/issues", json={"type": "task", "title": "Refunds"}, headers=ada.headers)).json()
    claude.edits = {"src/refunds.py": "def refund(amount):\n    return amount\n"}
    done = await _approve(db_client, base, (await db_client.post(
        f"{base}/coding/issues/{task['key']}/runs", json={}, headers=ada.headers)).json(), ada.headers)
    assert done["status"] == "failed" and "keeps them out" in (done["error"] or ""), done
