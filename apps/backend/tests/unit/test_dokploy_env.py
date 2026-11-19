"""deploy/dokploy.env.example lists every variable deploy/docker-compose.dokploy.yml reads, marks every one the
compose file requires as REQUIRED, and names nothing the compose file ignores (a setting there that never
reaches a container would silently do nothing)."""

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[4] / "deploy"
COMPOSE = (DEPLOY / "docker-compose.dokploy.yml").read_text()
EXAMPLE = (DEPLOY / "dokploy.env.example").read_text()
USE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(:?[-?])?[^}]*\}")


def _used() -> dict[str, bool]:
    used: dict[str, bool] = {}
    for name, operator in USE.findall(COMPOSE):
        used[name] = used.get(name, False) or "?" in operator
    # Build secrets read from the environment by name.
    for name in re.findall(r"^\s+environment: ([A-Z_][A-Z0-9_]*)$", COMPOSE, re.M):
        used[name] = True
    return used


def _listed() -> dict[str, bool]:
    """Each variable in the example, and whether the comment block just above it says REQUIRED."""
    listed: dict[str, bool] = {}
    comment: list[str] = []
    for line in EXAMPLE.splitlines():
        match = re.match(r"^#?\s*([A-Z_][A-Z0-9_]*)=", line)
        if match and not line.startswith("#   "):
            listed[match.group(1)] = any("REQUIRED" in text for text in comment)
            continue
        comment = [*comment, line] if line.startswith("#") else []
    return listed


def test_the_example_lists_every_variable_the_compose_file_reads():
    assert sorted(set(_used()) - set(_listed())) == []


def test_every_variable_the_compose_file_requires_is_marked_required():
    required = sorted(name for name, needed in _used().items() if needed)
    assert sorted(name for name in required if not _listed().get(name)) == []


def test_the_example_names_nothing_the_compose_file_ignores():
    assert sorted(set(_listed()) - set(_used())) == []
