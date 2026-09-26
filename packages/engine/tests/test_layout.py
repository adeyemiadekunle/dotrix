import pytest

from pmagent_engine.layout import AGENTS, InvalidPath, normalize_path, skeleton


def test_skeleton_has_the_prd_structure() -> None:
    files = skeleton("Kunemi", "Logistics platform")
    for path in (
        "project.md",
        "vision.md",
        "roadmap.md",
        "current-state.md",
        "requirements/product.md",
        "requirements/users.md",
        "requirements/business-rules.md",
        "architecture/overview.md",
        "decisions/README.md",
        "progress/completed.md",
        "issues/README.md",
        "sprints/README.md",
        "agent-rules/base.md",
    ):
        assert path in files, path
    assert {f"agent-rules/{a}.md" for a in AGENTS} <= set(files)
    assert all(normalize_path(p) == p for p in files)  # every skeleton path is valid


def test_project_name_and_readme_are_filled_in() -> None:
    files = skeleton("Kunemi", "Logistics platform", readme="# Kunemi\nHello")
    assert files["project.md"].startswith("# Kunemi\n\nLogistics platform")
    assert "Imported from the repository README" in files["project.md"]
    assert "You are working on the Kunemi project." in files["agent-rules/base.md"]
    assert "{project_name}" not in "".join(files.values())


@pytest.mark.parametrize(
    "path", ["requirements/product.md", "decisions/ADR-001.md", "docs/normalized/spec.md", "a.yaml"]
)
def test_valid_paths(path: str) -> None:
    assert normalize_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd.md",
        "../secrets.md",
        "requirements/../../x.md",
        "requirements\\product.md",
        ".hidden.md",
        "requirements/.env.md",
        "requirements//product.md",
        "report.pdf",
        "script.py",
        "a" * 301 + ".md",
    ],
)
def test_invalid_paths(path: str) -> None:
    with pytest.raises(InvalidPath):
        normalize_path(path)
