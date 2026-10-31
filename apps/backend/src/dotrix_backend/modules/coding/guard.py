"""What a coding run's changes may not touch, checked before anything is committed or pushed.

The sandbox can't see these rules (it only edits files), so the worker checks the agent's
changes: `.dotrix/` lives on the platform and never goes into a code repo, CI configuration
(all of `.github/`, other CI systems' files) could leak the repo's secrets when the PR's checks
run, and `.git` is git's own. Files CI runs without being CI configuration (build scripts, test
setup) can't be refused without making most runs useless, so a person accepts a turn that changes
them before it's pushed, in every approval mode (`needs_a_person`), and the PR names them.
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

MAX_FILES = 500
MAX_PATCH_BYTES = 8_000_000

# Other CI systems' configuration, at the repo's root.
CI_CONFIG = frozenset({
    ".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml", "Jenkinsfile",
    ".drone.yml", ".woodpecker.yml", "appveyor.yml", ".appveyor.yml", "cloudbuild.yaml", "buildspec.yml",
    ".cirrus.yml", "codemagic.yaml", "bitrise.yml", "wercker.yml",
})
CI_CONFIG_DIRS = frozenset({
    ".github", ".circleci", ".buildkite", ".gitlab", ".woodpecker", ".azure-pipelines", ".semaphore", ".tekton",
    ".harness", ".gitea", ".forgejo",
})
# Files whose code CI runs when it builds or tests (matched on the file name, anywhere).
CI_SENSITIVE = (
    "package.json", ".npmrc", ".yarnrc*", "Makefile", "*.mk", "justfile", "Taskfile.yml", "Rakefile",
    "conftest.py", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "noxfile.py", ".pre-commit-config.yaml",
    "Dockerfile*", "*.dockerfile", "docker-compose*.yml", "compose*.yml", "build.gradle*", "settings.gradle*",
    "pom.xml", "build.rs", "Cargo.toml", "go.mod", "Gemfile", ".husky", "lefthook.yml",
    "vitest.config.*", "jest.config.*", "playwright.config.*", "pytest.ini",
)


def refused(path: str) -> str | None:
    """Why a changed path isn't allowed in a coding run's PR, or None."""
    parts = PurePosixPath(path).parts
    if ".dotrix" in parts:
        return f"{path}: .dotrix/ stays on the platform, never in a code repo"
    if ".git" in parts:
        return f"{path}: git's own folder"
    if parts and (parts[0] in CI_CONFIG_DIRS or path in CI_CONFIG):
        return f"{path}: CI configuration isn't changed by coding runs (it would run with the repo's secrets)"
    return None


def ci_sensitive(paths: list[str]) -> list[str]:
    """The changed files CI may run (build scripts, test setup): for a person to review first."""
    return [path for path in paths if any(fnmatch(part, pattern) for part in PurePosixPath(path).parts
                                          for pattern in CI_SENSITIVE)]


def needs_a_person(approval_mode: str, paths: list[str]) -> tuple[bool, list[str]]:
    """Whether a turn's checked changes wait for a person to accept them, and the CI-sensitive files
    that make them: in Manual every turn waits; in Accept edits and Auto, a turn that changes files CI
    runs waits too (its PR's checks would run that code with the repo's secrets)."""
    sensitive = ci_sensitive(paths)
    return approval_mode == "manual" or bool(sensitive), sensitive


def check(paths: list[str]) -> list[str]:
    """Every reason the changes can't be pushed (empty: they can)."""
    reasons = [reason for path in paths if (reason := refused(path))]
    if len(paths) > MAX_FILES:
        reasons.append(f"{len(paths)} files changed, more than {MAX_FILES}")
    return reasons
