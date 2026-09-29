"""CLI <-> platform: device login, mirroring .pmagent/, the issue board, and the MCP server."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import PID, WS, FakePlatform, issue, sha  # noqa: E402

from pmagent_cli.board import PlatformBoard  # noqa: E402
from pmagent_cli.platform import Credential, PlatformError, device_login  # noqa: E402
from pmagent_cli.sync import STATE_FILE, LinkState, pull  # noqa: E402


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform()


@pytest.fixture
def state() -> LinkState:
    return LinkState(api_url="http://fake", workspace_id=WS, project_id=PID, project_key="KUN", project_name="Kunemi")


# -- device login ----------------------------------------------------------------------


def test_device_login_waits_for_approval(platform: FakePlatform) -> None:
    platform.device_polls = ["authorization_pending", "slow_down", "ok"]
    shown, slept = [], []
    credential = device_login(
        platform.client(token=None),
        show=lambda code, uri, complete: shown.append((code, uri)),
        open_browser=False,
        sleep=slept.append,
    )
    assert credential == Credential("pmat_new", "tok-1")
    assert shown == [("BCDF-GHJK", "http://fake/device")]
    assert slept == [5.0, 5.0, 10.0]  # slow_down adds 5 seconds


def test_device_login_denied(platform: FakePlatform) -> None:
    platform.device_polls = ["access_denied"]
    with pytest.raises(PlatformError) as exc:
        device_login(platform.client(None), show=lambda *a: None, open_browser=False, sleep=lambda s: None)
    assert exc.value.code == "access_denied"


# -- pull ---------------------------------------------------------------------------------


def test_first_pull_then_only_changes(platform: FakePlatform, state: LinkState, tmp_path: Path) -> None:
    platform.put("project.md", "# Kunemi\n")
    platform.put("requirements/product.md", "# Product\n")
    client = platform.client()

    first = pull(client, state, tmp_path)
    assert sorted(first.updated) == ["project.md", "requirements/product.md"]
    assert (tmp_path / "requirements" / "product.md").read_text() == "# Product\n"
    assert state.revision == platform.revision and (tmp_path / STATE_FILE).exists()

    platform.put("vision.md", "Move parcels fast.")
    platform.requests.clear()
    second = pull(client, LinkState.load(tmp_path), tmp_path)
    assert second.updated == ["vision.md"]
    assert f"since_revision={first.revision}" in str(platform.requests[0].url)
    downloads = [r for r in platform.requests if "/files/" in r.url.path]
    assert len(downloads) == 1  # unchanged files aren't fetched again


def test_deletions_are_mirrored(platform: FakePlatform, state: LinkState, tmp_path: Path) -> None:
    platform.put("roadmap.md", "x")
    client = platform.client()
    pull(client, state, tmp_path)
    platform.remove("roadmap.md")
    result = pull(client, state, tmp_path)
    assert result.deleted == ["roadmap.md"] and not (tmp_path / "roadmap.md").exists()


def test_local_edits_are_never_overwritten_silently(platform: FakePlatform, state: LinkState, tmp_path: Path) -> None:
    platform.put("vision.md", "platform v1")
    client = platform.client()
    pull(client, state, tmp_path)
    (tmp_path / "vision.md").write_text("my local edit")
    platform.put("vision.md", "platform v2")

    result = pull(client, state, tmp_path)
    assert result.conflicts == ["vision.md"]
    assert (tmp_path / "vision.md").read_text() == "my local edit"
    assert state.revision < platform.revision  # not advanced: reported again next time
    assert pull(client, state, tmp_path).conflicts == ["vision.md"]

    forced = pull(client, state, tmp_path, force=True)
    assert forced.updated == ["vision.md"] and (tmp_path / "vision.md").read_text() == "platform v2"
    assert state.revision == platform.revision and state.files["vision.md"] == sha("platform v2")


def test_local_file_that_already_matches_is_adopted(platform: FakePlatform, state: LinkState, tmp_path: Path) -> None:
    (tmp_path / "project.md").write_bytes(b"# Kunemi\n")  # exact bytes; write_text adds \r on Windows
    platform.put("project.md", "# Kunemi\n")
    result = pull(platform.client(), state, tmp_path)
    assert result.updated == [] and result.conflicts == [] and state.files["project.md"] == sha("# Kunemi\n")


def test_unexpected_paths_are_refused(platform: FakePlatform, state: LinkState, tmp_path: Path) -> None:
    platform.put("../escape.md", "x")
    with pytest.raises(PlatformError):
        pull(platform.client(), state, tmp_path)
    assert not (tmp_path.parent / "escape.md").exists()


# -- board --------------------------------------------------------------------------------


def test_board_acts_as_the_agent(platform: FakePlatform, state: LinkState) -> None:
    platform.issues = {"KUN-1": issue("KUN-1")}
    board = PlatformBoard(platform.client(), state, "claude-code")
    claimed = board.claim("KUN-1")
    assert claimed["assignee_agent"] == "claude-code" and claimed["status"] == "in_progress"
    board.comment("KUN-1", "PR open")
    board.review("KUN-1", "Built the lookup; run the tests", pr_url="https://github.com/x/y/pull/7")
    assert platform.bodies("/claim")[0] == {"key": "KUN-1", "as_agent": "claude-code"}
    assert platform.bodies("/comments")[0] == {"body": "PR open", "as_agent": "claude-code"}
    review = platform.bodies("/KUN-1")[-1]
    assert review["status"] == "review" and review["as_agent"] == "claude-code"
    assert review["links"] == [{"kind": "pr", "url": "https://github.com/x/y/pull/7"}]
    with pytest.raises(ValueError):
        board.done("KUN-1")  # only a person closes


def test_board_rejects_unknown_agents(platform: FakePlatform, state: LinkState) -> None:
    with pytest.raises(ValueError):
        PlatformBoard(platform.client(), state, "gpt-bot")


# -- MCP server in platform mode --------------------------------------------------------


def test_mirror_pulls_on_start_even_just_after_boot(
    platform: FakePlatform, state: LinkState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """time.monotonic() counts from boot on Linux; a freshly booted machine must still pull."""
    from pmagent_cli import mcp_server
    from pmagent_engine.config import ProjectConfig

    monkeypatch.setattr(mcp_server.time, "monotonic", lambda: 5.0)
    platform.put("project.md", "# Kunemi")
    config = ProjectConfig(name="Kunemi", root_dir=str(tmp_path))
    Path(config.pmagent_dir).mkdir()
    state.save(config.pmagent_dir)
    mcp_server.build_server(config, "codex", client=platform.client())
    assert (Path(config.pmagent_dir) / "project.md").read_text() == "# Kunemi"


async def test_mcp_task_tools_use_the_platform_board(platform: FakePlatform, state: LinkState, tmp_path: Path) -> None:
    from pmagent_cli.mcp_server import build_server
    from pmagent_engine.config import ProjectConfig

    platform.put("project.md", "# Kunemi\nLogistics.")
    platform.issues = {"KUN-7": issue("KUN-7", title="Postcode lookup")}
    config = ProjectConfig(name="Kunemi", root_dir=str(tmp_path))
    Path(config.pmagent_dir).mkdir()
    state.save(config.pmagent_dir)

    server = build_server(config, "codex", client=platform.client())
    # The mirror was pulled when the server started.
    assert (Path(config.pmagent_dir) / "project.md").read_text() == "# Kunemi\nLogistics."

    def result(raw):  # MCP call_tool returns (content, structured) in recent versions
        return raw[1] if isinstance(raw, tuple) else raw

    listed = result(await server.call_tool("list_tasks", {}))
    assert "KUN-7" in str(listed)
    claimed = result(await server.call_tool("claim_task", {"task_id": "KUN-7"}))
    assert "in_progress" in str(claimed)
    assert platform.bodies("/claim")[0] == {"key": "KUN-7", "as_agent": "codex"}
    doc = result(await server.call_tool("read_doc", {"path": "project.md"}))
    assert "Logistics." in str(doc)
    from pmagent_cli.mcp_server import ToolError

    with pytest.raises(ToolError, match="internal"):  # link state is never readable
        await server.call_tool("read_doc", {"path": STATE_FILE})


# -- a project moved to another workspace --------------------------------------------------


def test_follow_move_updates_the_link(platform: FakePlatform, state: LinkState, tmp_path: Path) -> None:
    from pmagent_cli.sync import follow_move

    assert follow_move(platform.client(), state, tmp_path) is None  # still where it was
    assert state.workspace_id == WS

    platform.moved_to = {"id": "ws-2", "slug": "acme-ab12cd", "name": "Acme", "role": "admin", "kind": "organization",
                         "projects": [{"id": PID, "key": "KUN", "name": "Kunemi app"}]}
    assert follow_move(platform.client(), state, tmp_path) == "Acme"
    saved = LinkState.load(tmp_path)
    assert saved is not None and saved.workspace_id == "ws-2" and saved.project_name == "Kunemi app"
    assert state.issues_path == f"/workspaces/ws-2/projects/{PID}/issues"


def test_follow_move_leaves_a_project_it_cant_find(platform: FakePlatform, state: LinkState, tmp_path: Path) -> None:
    from pmagent_cli.sync import follow_move

    platform.moved_to = {"id": "ws-2", "slug": "other", "name": "Other", "role": "member", "kind": "organization", "projects": []}
    assert follow_move(platform.client(), state, tmp_path) is None
    assert state.workspace_id == WS


def test_commands_follow_a_moved_project(linked_repo: Path, platform: FakePlatform) -> None:
    from typer.testing import CliRunner

    from pmagent_cli import cli as cli_module

    platform.moved_to = {"id": "ws-2", "slug": "acme", "name": "Acme", "role": "admin", "kind": "organization",
                         "projects": [{"id": PID, "key": "KUN", "name": "Kunemi"}]}
    result = CliRunner().invoke(cli_module.app, ["pull", "--project", str(linked_repo)])
    assert "KUN moved to the Acme workspace; link updated." in result.output
    assert LinkState.load(linked_repo / ".pmagent").workspace_id == "ws-2"
