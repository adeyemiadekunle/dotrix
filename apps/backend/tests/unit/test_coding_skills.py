import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dotrix_backend.modules.coding.sandbox import LocalSandbox, SandboxError
from dotrix_backend.modules.coding.skills import catalog_brief, materialize


async def test_skills_are_loaded_as_files_without_prompting_full_content(tmp_path):
    text = "Description: Team procedure\n\nA long private procedure, only needed for this task."
    digest = hashlib.sha256(text.encode()).hexdigest()
    snapshot = {"../a skill": {"content": text, "sha256": digest}}
    catalog = catalog_brief(snapshot)
    assert "Team procedure" in catalog and "A long private procedure" not in catalog
    import uuid

    source = tmp_path / "repo"
    source.mkdir()
    (source / "json.py").write_text("raise RuntimeError('repository modules must not run during skill setup')")
    tool = SimpleNamespace(sandbox_env=lambda key: {})
    box = await LocalSandbox().open(uuid.uuid4(), source, tool, "unused")
    try:
        brief = await materialize(box, snapshot)
        path = brief.splitlines()[-1].split(": ", 1)[1]
        result = await box.exec(["cat", path], timeout=10)
        assert result.stdout == text
        assert path.endswith(f"/{digest}.md")
        assert [path.name for path in (box.root / "repo").iterdir()] == ["json.py"]
        second = await materialize(box, snapshot)
        assert second != brief  # A warm sandbox gets a fresh directory, never stale paths.
    finally:
        await box.close()


async def test_tampered_snapshot_is_rejected_before_starting_a_process():
    box = SimpleNamespace(exec=AsyncMock())
    with pytest.raises(SandboxError, match="integrity"):
        await materialize(box, {"skill": {"content": "changed", "sha256": "a" * 64}})
    box.exec.assert_not_called()


async def test_failed_materialization_refuses_the_turn():
    text = "Instructions"
    snapshot = {"skill": {"content": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}}
    box = SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(code=1, stdout="", truncated=False)))
    with pytest.raises(SandboxError, match="prepare"):
        await materialize(box, snapshot)


async def test_pinned_resources_are_materialized_and_hash_checked(tmp_path):
    import uuid

    source = tmp_path / "repo"
    source.mkdir()
    text, resource = "Description: Test\nResources: templates/check.md", "# Original template"
    digest = hashlib.sha256(text.encode()).hexdigest()
    pinned = {"content": resource, "sha256": hashlib.sha256(resource.encode()).hexdigest()}
    snapshot = {name: {"content": text, "sha256": digest, "resources": {"templates/check.md": pinned}}
                for name in ["one", "two"]}
    box = await LocalSandbox().open(uuid.uuid4(), source, SimpleNamespace(sandbox_env=lambda key: {}), "unused")
    try:
        brief = await materialize(box, snapshot)
        paths = [line.split(": ", 1)[1] for line in brief.splitlines() if line.startswith("  Resource ")]
        assert len(paths) == 2 and paths[0] != paths[1]
        for path in paths:
            assert (await box.exec(["cat", path], timeout=10)).stdout == resource
    finally:
        await box.close()


async def test_snapshot_resources_and_missing_references(monkeypatch):
    from dotrix_backend.modules.agents import skill_snapshots

    row = SimpleNamespace(path="agent-rules/skills/team/templates/check.md", content="# Template", deleted=False)
    repo = SimpleNamespace(list_files=AsyncMock(return_value=[row]))
    monkeypatch.setattr(skill_snapshots, "KnowledgeRepository", lambda session: repo)
    text = "Description: Team\nResources: templates/check.md, references/missing.md\nRequires: browser"
    snapshot = await skill_snapshots.with_resources(None, "project", {"team": text})
    assert snapshot["team"]["resources"]["templates/check.md"]["content"] == "# Template"
    assert snapshot["team"]["missing_resources"] == ["references/missing.md"]
    from dotrix_backend.modules.coding.capabilities import skills
    assert skills(snapshot, [{"id": "browser", "available": False}])[0]["unavailable_tools"] == ["browser"]
    with pytest.raises(Exception, match="literal relative"):
        await skill_snapshots.with_resources(None, "project", {"team": "Resources: ../secret.md"})


async def test_chat_resource_reads_stay_inside_the_authorized_snapshot():
    from dotrix_backend.modules.agents.knowledge_tools import build_knowledge_tools

    tools = build_knowledge_tools(None, workspace_id="workspace", project_id="project", embedder=None,
                                  skill_snapshot={"team": "Original procedure"},
                                  resource_snapshot={"team": {"references/check.md": {"content": "Pinned checklist"}}})
    read = next(tool for tool in tools if tool.__name__ == "read_skill")
    assert await read("team", "references/check.md") == "Pinned checklist"
    assert "references/check.md" in await read("team")
    assert "No pinned resource" in await read("team", "../private.md")
    assert "authorized catalog" in await read("other", "references/check.md")


def test_plan_capabilities_report_unavailable_writes_and_browser():
    from dotrix_backend.core.settings import Settings
    from dotrix_backend.modules.coding.capabilities import describe, instructions
    from dotrix_backend.modules.coding.models import CodingAgent, CodingLocation

    run = SimpleNamespace(agent=CodingAgent.CLAUDE_CODE, model="anthropic:claude-haiku-5-5",
                          location=CodingLocation.CLOUD, work_mode="plan")
    capabilities = describe(run, Settings(database_url="postgresql+asyncpg://localhost/unused", jwt_secret="test-only-secret-for-skills-and-capabilities"))
    state = {item["id"]: item["available"] for item in capabilities}
    assert state["repository.read"] and state["terminal"]
    assert not state["repository.write"] and not state["browser"] and not state["publication"]
    text = "Description: Browser procedure"
    snapshot = {"browser-skill": {"content": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                  "requires": ["browser"]}}
    assert "requires unavailable tools: browser" in instructions(capabilities, snapshot)


async def test_resource_changes_do_not_change_a_pinned_run(monkeypatch):
    from dotrix_backend.modules.agents import skill_snapshots

    text = "Description: Team\nResources: references/check.md"
    row = SimpleNamespace(path="agent-rules/skills/team/references/check.md", content="Original resource", deleted=False)
    repo = SimpleNamespace(list_files=AsyncMock(return_value=[row]))
    monkeypatch.setattr(skill_snapshots, "KnowledgeRepository", lambda session: repo)
    monkeypatch.setattr(skill_snapshots, "resolve", AsyncMock(return_value={"team": text}))
    session = SimpleNamespace(commit=AsyncMock())
    run = SimpleNamespace(skill_snapshot=None, workspace_id="workspace", project_id="project")
    await skill_snapshots.pin(session, run, None)
    row.content = "Changed resource"
    await skill_snapshots.pin(session, run, None)
    assert run.skill_snapshot["team"]["resources"]["references/check.md"]["content"] == "Original resource"
    assert repo.list_files.await_count == 1


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "a/../../b", "a//b", "C:/secret", "a\\b", ".git/config"])
def test_skill_resources_reject_unsafe_paths(path):
    from dotrix_engine.skills import skill_resources

    with pytest.raises(ValueError, match="literal relative"):
        skill_resources(f"Resources: {path}")
