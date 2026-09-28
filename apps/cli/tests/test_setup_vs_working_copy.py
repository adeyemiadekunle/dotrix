"""Project setup (owners/admins) vs. connecting a working copy (anyone), from the CLI."""
from __future__ import annotations

import functools
import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent))

from fake_platform import PID, FakePlatform  # noqa: E402

from pmagent_cli import cli as cli_module  # noqa: E402
from pmagent_cli import repo as repo_facts  # noqa: E402
from pmagent_cli.agent_client import PlatformAgent  # noqa: E402
from pmagent_cli.sync import STATE_FILE, LinkState  # noqa: E402

REMOTE = "https://ada:ghp_secret@github.com/acme/kunemi.git"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "kunemi"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", REMOTE)
    (repo / "README.md").write_text("# Kunemi\nParcel delivery.\n")
    (repo / "package.json").write_text(json.dumps({"name": "kunemi", "dependencies": {"next": "16"}, "scripts": {"dev": "x"}}))
    (repo / "apps" / "api").mkdir(parents=True)
    (repo / "apps" / "api" / "pyproject.toml").write_text('[project]\nname = "api"\ndependencies = ["fastapi"]\n')
    (repo / "apps" / "api" / "main.py").write_text("SECRET_LOGIC = 'never sent'\n")
    (repo / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres:17\n    environment:\n      POSTGRES_PASSWORD: hunter2\n")
    (repo / ".env").write_text("API_KEY=sk-live-should-never-leave\n")
    (repo / ".gitignore").write_text(".env\n")
    git(repo, "add", ".")
    return repo


@pytest.fixture
def platform(monkeypatch) -> FakePlatform:
    fake = FakePlatform()
    fake.put("project.md", "# Kunemi\n")
    monkeypatch.setattr(cli_module.PlatformClient, "signed_in", classmethod(lambda cls, url=None, store=None: fake.client()))
    monkeypatch.setattr(cli_module, "PlatformAgent", functools.partial(PlatformAgent, sleep=lambda s: None))
    return fake


def run(*args: str, input: str | None = None):
    return CliRunner().invoke(cli_module.app, list(args), input=input)


# -- repo facts -------------------------------------------------------------------------


def test_credentials_are_stripped_locally() -> None:
    assert repo_facts.strip_credentials(REMOTE) == "https://github.com/acme/kunemi.git"
    assert repo_facts.strip_credentials("git@github.com:acme/kunemi.git") == "git@github.com:acme/kunemi.git"


@pytest.mark.parametrize(("name", "key"), [("kunemi", "KUN"), ("kunemi-web", "KW"), ("2fast", "P2FA"), ("a", "AX")])
def test_suggested_keys(name: str, key: str) -> None:
    assert repo_facts.suggest_key(name) == key


def test_repo_summary_has_structure_but_no_code_or_secrets(checkout: Path) -> None:
    summary = repo_facts.repo_summary(checkout)
    assert "apps/api/  (2 files)" in summary and "## apps/api/pyproject.toml" in summary
    assert '"next": "16"' in summary and "- db: postgres:17" in summary and "Parcel delivery." in summary
    for secret in ("never sent", "hunter2", "sk-live", ".env"):
        assert secret not in summary, secret


# -- connect: working copies -------------------------------------------------------------


def test_member_connects_to_the_existing_project(checkout: Path, platform: FakePlatform) -> None:
    platform.workspaces[0]["role"] = "member"
    platform.projects = [{"id": PID, "key": "KUN", "name": "Kunemi", "description": "", "model": "m",
                          "repo_url": "https://github.com/acme/kunemi"}]
    result = run("connect", str(checkout))
    assert result.exit_code == 0, result.output
    assert "This repo belongs to KUN (Kunemi) in Kunemi" in result.output
    assert not [r for r in platform.requests if r.method == "POST"]  # nothing created or run
    state = LinkState.load(checkout / ".pmagent")
    assert state.project_key == "KUN" and (checkout / ".pmagent" / "project.md").exists()
    lookup = next(r for r in platform.requests if r.url.params.get("repo_url"))
    assert "ghp_secret" not in str(lookup.url)  # credentials never leave the machine


def test_member_without_a_project_is_sent_to_an_owner(checkout: Path, platform: FakePlatform) -> None:
    platform.workspaces[0]["role"] = "member"
    result = run("connect", str(checkout))
    assert result.exit_code == 1
    assert "owners and admins" in result.output
    assert not (checkout / ".pmagent" / STATE_FILE).exists()
    assert not [r for r in platform.requests if r.method == "POST"]


def test_owner_sets_up_the_project_when_none_exists(checkout: Path, platform: FakePlatform) -> None:
    result = run("connect", str(checkout), input="y\nKunemi\nKUN\nParcel delivery platform\n")
    assert result.exit_code == 0, result.output
    [created] = platform.bodies("/projects")
    assert created["key"] == "KUN" and created["source"] == "existing_repo"
    assert created["repo_url"] == "https://github.com/acme/kunemi.git"  # stripped of credentials
    assert created["readme"].startswith("# Kunemi")
    assert "pmagent architecture draft" in result.output  # next setup steps
    assert platform.runs_started == []  # connecting never starts an architecture draft
    assert LinkState.load(checkout / ".pmagent").project_id == PID


def test_connect_needs_a_git_repo(tmp_path: Path, platform: FakePlatform) -> None:
    result = run("connect", str(tmp_path))
    assert result.exit_code == 1 and "isn't a git repository" in result.output


# -- setup work on a linked repo ------------------------------------------------------------


@pytest.fixture
def linked(checkout: Path, platform: FakePlatform) -> Path:
    platform.projects = [{"id": PID, "key": "KUN", "name": "Kunemi", "description": "", "model": "m",
                          "repo_url": "https://github.com/acme/kunemi"}]
    assert run("connect", str(checkout)).exit_code == 0
    platform.requests.clear()
    return checkout


def test_docs_add_uploads_and_pulls(linked: Path, platform: FakePlatform, tmp_path: Path) -> None:
    doc = tmp_path / "spec.docx"
    doc.write_bytes(b"PK fake docx")
    result = run("docs-add", str(doc), "--project", str(linked))
    assert result.exit_code == 0, result.output
    assert "-> .pmagent/docs/normalized/spec.md" in result.output
    assert (linked / ".pmagent" / "docs" / "normalized" / "spec.md").read_text() == "imported spec.docx"


def test_docs_add_waits_for_the_background_conversion(
    linked: Path, platform: FakePlatform, tmp_path: Path, monkeypatch
) -> None:
    naps: list[float] = []
    monkeypatch.setattr(cli_module, "_sleep", naps.append)
    platform.document_states = [{"status": "converting"}, {"status": "ready", "knowledge_version": 1}]
    doc = tmp_path / "spec.pdf"
    doc.write_bytes(b"%PDF fake")
    result = run("docs-add", str(doc), "--project", str(linked))
    assert result.exit_code == 0, result.output
    assert len(naps) == 2  # it checked back until the platform had converted it
    assert "-> .pmagent/docs/normalized/spec.md (v1)" in result.output
    assert (linked / ".pmagent" / "docs" / "normalized" / "spec.md").read_text() == "imported spec.pdf"


def test_docs_add_reports_a_failed_conversion(linked: Path, platform: FakePlatform, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "_sleep", lambda _s: None)
    platform.document_states = [{"status": "failed", "error": "This PDF is password-protected"}]
    doc = tmp_path / "locked.pdf"
    doc.write_bytes(b"%PDF fake")
    result = run("docs-add", str(doc), "--project", str(linked))
    assert result.exit_code == 1
    assert "locked.pdf: couldn't convert it: This PDF is password-protected" in result.output


def test_architecture_draft_shows_the_summary_first(linked: Path, platform: FakePlatform) -> None:
    platform.agent_script = [{"status": "completed", "reply": "Drafted architecture/overview.md."}]
    declined = run("architecture", "draft", "--project", str(linked), input="n\n")
    assert declined.exit_code == 0, declined.output
    assert "no source code" in declined.output and platform.runs_started == [{}]  # sent without the summary

    platform.runs_started.clear()
    sent = run("architecture", "draft", "--project", str(linked), input="y\n")
    assert sent.exit_code == 0, sent.output
    assert "apps/api/pyproject.toml" in platform.runs_started[0]["repo_summary"]
    assert "Drafted architecture/overview.md." in sent.output


def test_issue_list_mine_for_a_person(linked: Path, platform: FakePlatform) -> None:
    result = run("issue", "list", "--mine", "--project", str(linked))
    assert result.exit_code == 0, result.output
    listing = next(r for r in platform.requests if r.url.path.endswith("/issues"))
    assert listing.url.params["assignee"] == "user-1"
