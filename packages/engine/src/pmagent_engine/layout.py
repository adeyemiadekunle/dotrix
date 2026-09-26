"""The `.pmagent/` source-of-truth layout (PRD "Folder structure").

Pure data: no filesystem or database access, so the platform, the CLI, and
agent runs all agree on the same skeleton and path rules. Paths are relative
to the `.pmagent/` root, POSIX style, e.g. `requirements/product.md`.
"""
from __future__ import annotations

import re
from importlib import resources
from pathlib import PurePosixPath

AGENTS = (
    "project-manager",
    "product",
    "architecture",
    "research",
    "reviewer",
    "documentation",
    "coding",
)

# Text formats only: originals of uploaded docs (PDF, DOCX, ...) live in blob
# storage; their normalised markdown lives here under docs/.
ALLOWED_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".yaml", ".yml", ".json", ".csv"})
MAX_PATH_LENGTH = 300
MAX_FILE_BYTES = 1_000_000
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class InvalidPath(ValueError):
    pass


def normalize_path(path: str) -> str:
    """Validate a `.pmagent/`-relative path and return its canonical form.

    Rejects absolute paths, `..`, backslashes, hidden segments, and non-text
    suffixes, so a path can never escape the project or collide by spelling.
    """
    raw = path.strip()
    if not raw or len(raw) > MAX_PATH_LENGTH:
        raise InvalidPath("Path must be 1-300 characters")
    if raw.startswith("/") or "\\" in raw:
        raise InvalidPath("Use a relative path with forward slashes, e.g. requirements/product.md")
    parts = raw.split("/")
    if any(not _SEGMENT.match(p) for p in parts):
        raise InvalidPath(
            "Each path segment must start with a letter or digit and use only "
            "letters, digits, '.', '_' or '-'"
        )
    pure = PurePosixPath(*parts)
    if pure.suffix.lower() not in ALLOWED_SUFFIXES:
        raise InvalidPath(f"Only text files are stored: {', '.join(sorted(ALLOWED_SUFFIXES))}")
    return pure.as_posix()


def _folder_readme(title: str, owner: str, body: str) -> str:
    return f"# {title}\n\nOwner: **{owner}**\n\n{body}\n"


def default_rules(project_name: str) -> dict[str, str]:
    """`agent-rules/*.md` shipped with the engine, with the project name filled in."""
    files: dict[str, str] = {}
    package = resources.files("pmagent_engine.rules")
    for name in ("base", *AGENTS):
        text = package.joinpath(f"{name}.md").read_text(encoding="utf-8")
        files[f"agent-rules/{name}.md"] = text.replace("{project_name}", project_name)
    return files


def skeleton(name: str, description: str = "", readme: str | None = None) -> dict[str, str]:
    """Every file a new project starts with, as {path: content}."""
    project_md = f"# {name}\n\n{description or '_One-line description of the project._'}\n"
    if readme:
        project_md += f"\n## Imported from the repository README\n\n{readme.strip()}\n"

    files: dict[str, str] = {
        "project.md": project_md,
        "vision.md": "# Vision\n\n_What this project is for, who it serves, and what success looks like._\n",
        "roadmap.md": "# Roadmap\n\n_Phases, milestones, and what's next._\n",
        "current-state.md": "# Current state\n\nPhase: _not started_\n\n_Headline status, updated by the Project Manager._\n",
        "requirements/product.md": "# Product requirements\n",
        "requirements/users.md": "# Users\n\n_Who uses the product and what they need._\n",
        "requirements/business-rules.md": "# Business rules\n",
        "requirements/modules/README.md": _folder_readme(
            "Modules", "Product", "One file per module or workstream, e.g. `drivers.md`."
        ),
        "architecture/overview.md": "# Architecture overview\n\n_Stack, main components, and how they relate._\n",
        "architecture/database.md": "# Database\n",
        "architecture/api.md": "# API\n",
        "architecture/integrations.md": "# Integrations\n",
        "decisions/README.md": _folder_readme(
            "Decisions (ADRs)",
            "Documentation",
            "One file per decision: `ADR-001.md`, `ADR-002.md`, ... Never edited away; "
            "a changed decision gets a new ADR that supersedes the old one.",
        ),
        "research/README.md": _folder_readme(
            "Research", "Research", "Findings, with verified facts and sources kept apart from assumptions."
        ),
        "reviews/README.md": _folder_readme("Reviews", "Reviewer", "One report per code review."),
        "progress/completed.md": "# Completed\n",
        "progress/in-progress.md": "# In progress\n",
        "progress/blocked.md": "# Blocked\n",
        "issues/README.md": _folder_readme(
            "Issues", "Project Manager", "One file per issue: `KEY-1.md`, `KEY-2.md`, ..."
        ),
        "sprints/README.md": _folder_readme("Sprints", "Project Manager", "One file per sprint."),
        "docs/README.md": _folder_readme(
            "Docs", "Documentation", "Index of ingested documents (normalised to markdown)."
        ),
    }
    files.update(default_rules(name))
    return files
