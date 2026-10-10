"""Project configuration for the PM Agent system.

Every connected project gets a `.dotrix/` folder at its root holding
`config.yaml` plus all project knowledge. It is the ONLY project-specific
thing; the agent prompts, tools, and CLI are shared across every project.

`.dotrix/` is never committed or pushed to the code host. It stays on this
machine (and, once the hosted platform exists, on the platform with this as a
synced mirror). `scaffold()` applies the git protections in gitguard.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .gitguard import protect

CONFIG_DIRNAME = ".dotrix"
CONFIG_FILENAME = "config.yaml"

SKELETON_DOCS = [
    "project.md", "vision.md", "roadmap.md", "current-state.md",
]
SKELETON_DIRS = [
    "requirements", "architecture", "decisions", "research", "progress",
    "tasks", "reviews", "docs/originals", "docs/normalized",
]


@dataclass
class ProjectConfig:
    name: str
    description: str = ""
    root_dir: str = "."          # repo root; .dotrix/ lives directly inside it
    model: str = "anthropic:claude-sonnet-5"

    @property
    def dotrix_dir(self) -> str:
        return os.path.join(self.root_dir, CONFIG_DIRNAME)

    @property
    def config_path(self) -> str:
        return os.path.join(self.dotrix_dir, CONFIG_FILENAME)

    def save(self) -> None:
        Path(self.dotrix_dir).mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.safe_dump(
                {"name": self.name, "description": self.description, "model": self.model},
                f,
            )

    @classmethod
    def load(cls, root_dir: str) -> ProjectConfig:
        path = os.path.join(root_dir, CONFIG_DIRNAME, CONFIG_FILENAME)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"No {CONFIG_DIRNAME}/ found at {root_dir}. Run "
                f"`dotrix init` or `dotrix connect {root_dir}` first."
            )
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        data.pop("root_dir", None)
        return cls(root_dir=root_dir, **data)


def scaffold(config: ProjectConfig, existing_readme: str | None = None) -> dict:
    """Create the .dotrix/ skeleton for a brand-new OR newly-connected project,
    and keep it out of git. Returns the git-protection report.

    Safe to re-run: never overwrites files that already exist.
    """
    base = Path(config.dotrix_dir)

    for rel_dir in SKELETON_DIRS:
        (base / rel_dir).mkdir(parents=True, exist_ok=True)

    for rel_doc in SKELETON_DOCS:
        p = base / rel_doc
        if not p.exists():
            p.write_text(f"# {rel_doc}\n\n_(empty — filled in as the project develops)_\n")

    project_md = base / "project.md"
    header = f"# {config.name}\n\n{config.description}\n"
    body = project_md.read_text()
    if body.strip().startswith("# project.md") or body.strip() == "":
        content = header
        if existing_readme:
            content += f"\n## Imported from existing README\n\n{existing_readme}\n"
        project_md.write_text(content)

    manifest = base / "docs" / "manifest.md"
    if not manifest.exists():
        manifest.write_text("# Ingested docs\n\n")

    config.save()
    return protect(config.root_dir, config.dotrix_dir)
