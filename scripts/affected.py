"""Select CI work from Git changes and workspace dependency edges. Standard library only.

Unknown source/config paths and missing diff history select everything. Documentation
changes still receive the always-running format/boundary/release guards.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = {"engine": "packages/engine", "cli": "apps/cli", "backend": "apps/backend"}


def workspace(root: Path = ROOT) -> tuple[dict[str, str], dict[str, set[str]], dict[str, str]]:
    paths = dict(PYTHON)
    names = {}
    manifests = {}
    for base in ("apps", "packages"):
        for path in sorted((root / base).glob("*/package.json")):
            data = json.loads(path.read_text())
            key = path.parent.name
            folder = str(path.parent.relative_to(root))
            if key in paths:
                raise ValueError(f"Ambiguous workspace component folder: {folder}")
            paths[key] = folder
            if not re.fullmatch(r"@dotrix/[a-z0-9-]+", data["name"]):
                raise ValueError(f"Unsupported workspace name in {path}")
            names[key] = data["name"]
            manifests[key] = data
    identifiers = {name: key for key, name in names.items()}
    for key, path in PYTHON.items():
        data = tomllib.loads((root / path / "pyproject.toml").read_text())
        identifiers[data["project"]["name"].lower().replace("_", "-")] = key
        manifests[key] = data["project"]
    dependencies = {key: set() for key in paths}
    for key, manifest in manifests.items():
        for field in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            for name in manifest.get(field, []):
                name = re.split(r"[\s\[<>=!~;]", name, maxsplit=1)[0].lower().replace("_", "-")
                if name in identifiers and identifiers[name] != key:
                    dependencies[key].add(identifiers[name])
    # A cross-language build dependency: the desktop bundles the Python CLI.
    dependencies["desktop"].add("cli")
    return paths, dependencies, names


def select(files: list[str] | None, root: Path = ROOT) -> dict:
    paths, dependencies, names = workspace(root)
    affected: set[str] = set()
    global_change = files is None
    infrastructure = False
    for path in files or []:
        if path in ("AGENTS.md", "CLAUDE.md", "README.md", "CHANGELOG.md", "LICENSE") or path.startswith("docs/"):
            continue
        owners = {key for key, folder in paths.items() if path.startswith(folder + "/")}
        if owners:
            affected.update(owners)
        elif path in ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "turbo.json", "tsconfig.base.json", "eslint.config.mjs", "knip.json"):
            affected.update(names)
        elif path in ("pyproject.toml", "uv.lock"):
            affected.update(PYTHON)
        elif path.startswith(("deploy/", "infra/")):
            infrastructure = True
            # Container/profile changes can alter server execution and browser tools.
            affected.add("backend")
        elif path.startswith("docs/") or path in (".gitignore", ".dockerignore"):
            continue
        else:
            # Lockfiles, workflows, tooling, unknown new components: never skip by guessing.
            global_change = True
    if global_change:
        affected.update(paths)
    while True:
        expanded = affected | {key for key, deps in dependencies.items() if deps & affected}
        if expanded == affected:
            break
        affected = expanded
    node = sorted(names[key] for key in affected if key in names)
    python_paths = [path + "/tests" for key, path in PYTHON.items() if key in affected]
    return {
        "components": sorted(affected), "node_packages": node, "python_paths": python_paths,
        "python": bool(python_paths), "node": bool(node), "cli": "cli" in affected,
        "desktop": "desktop" in affected,
        "e2e": bool({"backend", "web", "ui", "api-client"} & affected),
        "contract": bool({"backend", "api-client"} & affected),
        "infrastructure": infrastructure or global_change,
    }


def changed(base: str, head: str, root: Path = ROOT) -> list[str] | None:
    try:
        # Merge-base on PRs includes the whole branch, not just its newest commit.
        merge = subprocess.check_output(["git", "merge-base", base, head], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        result = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", merge, head, "--"], cwd=root)
        return [p.decode() for p in result.split(b"\0") if p]
    except (OSError, UnicodeError, subprocess.CalledProcessError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("BASE_SHA", "HEAD^"))
    parser.add_argument("--head", default=os.environ.get("HEAD_SHA", "HEAD"))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = select(None if args.all else changed(args.base, args.head))
    print(json.dumps(result, indent=2))
    if args.github_output:
        with args.github_output.open("a") as output:
            for key, value in result.items():
                output.write(f"{key}={json.dumps(value, separators=(',', ':'))}\n")
            output.write("node_filters=" + " ".join("--filter=" + name for name in result["node_packages"]) + "\n")
            output.write("python_targets=" + " ".join(result["python_paths"]) + "\n")


if __name__ == "__main__":
    main()
