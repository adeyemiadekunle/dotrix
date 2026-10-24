"""A repository's inventory: every tracked path at one commit, classified without a model.

The first step of the Repository Knowledge skill (docs/dotrix-repository-knowledge-skill.md):
before anything is explained, every tracked path is listed with what it is (kinds), which of the
required knowledge domains it is evidence for, and a status, so nothing in the declared scope is
skipped silently. Generated code, vendored dependencies, binaries, large files, submodules, and
symlinks stay in the inventory, excluded or marked with why. Nothing in the repository is run; the
classification reads paths, git's file modes, sizes, and the first bytes of a file.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .code import git

POLICY_VERSION = "inventory-1"  # bump when the rules below change what a path gets
MAX_TEXT_BYTES = 1_000_000  # larger files are listed, not read
SNIFF_BYTES = 8_000

# The domains every repository's knowledge must cover: evidence, a documented exclusion, or a gap.
DOMAINS: dict[str, str] = {
    "product": "Product and domain: purpose, users, vocabulary, capabilities, boundaries",
    "functional": "Functional requirements: journeys, roles, rules, states, inputs, outputs, errors",
    "non_functional": "Non-functional requirements: performance, availability, security, privacy, accessibility",
    "architecture": "Architecture: entrypoints, packages, services, module relationships, flows, jobs",
    "design": "Design and UX: screens, routes, components, design tokens, assets, accessibility",
    "tooling": "Tools and development: languages, runtimes, setup, build, lint, codegen, test commands",
    "dependencies": "Dependencies: internal packages, external dependencies and versions, external services",
    "apis": "APIs and contracts: routes, schemas, events, authentication, errors, versioning",
    "data": "Data: entities, schemas, migrations, persistence, retention, data movement",
    "quality": "Quality: test suites, fixtures, CI checks, requirement-to-test links",
    "delivery": "Delivery and operations: CI/CD, deployment, infrastructure, observability, runbooks",
    "decisions": "Decisions and history: ADRs, accepted decisions, known debt, contradictions",
}

# What's missing when a domain has no evidence in the repository: the gap says what to ask for.
GAP_HINTS: dict[str, str] = {
    "product": "No README or product document: ask the team what the product is for and who uses it",
    "functional": "No written requirements: behaviour can be described from the code, but not what is required",
    "non_functional": "No stated targets (performance, availability, security, accessibility): ask for them",
    "architecture": "No source code or architecture document was found",
    "design": "No styles, components, or design files: ask for the design specification",
    "tooling": "No build or tool configuration: ask how the project is set up and run",
    "dependencies": "No package manifest or lockfile",
    "apis": "No API routes, schemas, or contracts were found",
    "data": "No models, schemas, or migrations were found",
    "quality": "No tests or CI checks were found",
    "delivery": "No CI/CD, deployment, or infrastructure definitions: ask how it is released and run",
    "decisions": "No ADRs or decision records: decisions live elsewhere, or aren't written down",
}

LANGUAGES = {
    ".py": "Python", ".pyi": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".cts": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".swift": "Swift",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".fs": "F#", ".scala": "Scala", ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".m": "Objective-C", ".dart": "Dart", ".ex": "Elixir",
    ".exs": "Elixir", ".erl": "Erlang", ".clj": "Clojure", ".hs": "Haskell", ".lua": "Lua", ".r": "R",
    ".sql": "SQL", ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro", ".css": "CSS", ".scss": "SCSS", ".sass": "SCSS",
    ".less": "Less", ".html": "HTML", ".md": "Markdown", ".mdx": "Markdown", ".rst": "reStructuredText",
    ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".json": "JSON", ".proto": "Protocol Buffers",
    ".graphql": "GraphQL", ".gql": "GraphQL", ".tf": "Terraform", ".hcl": "HCL", ".prisma": "Prisma",
}

_BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".avif", ".psd", ".sketch", ".fig",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".wav", ".mov", ".webm", ".ogg", ".pdf",
    ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".whl", ".so", ".dylib", ".dll",
    ".exe", ".bin", ".o", ".a", ".class", ".pyc", ".wasm", ".db", ".sqlite", ".parquet",
}
_DESIGN_ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".avif", ".psd", ".sketch", ".fig",
                     ".woff", ".woff2", ".ttf", ".otf", ".eot"}
_VENDORED = re.compile(r"(^|/)(node_modules|vendor|third_party|bower_components|\.yarn/releases|site-packages)/")
_GENERATED_DIRS = re.compile(r"(^|/)(dist|build|out|\.next|\.nuxt|coverage|__pycache__|\.turbo|target)/")
_GENERATED_FILES = re.compile(r"(\.min\.(js|css)$|\.map$|\.pb\.go$|_pb2\.py$|\.g\.dart$|\.generated\.)")
_LOCKFILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "uv.lock", "poetry.lock",
              "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock", "composer.lock", "mix.lock", "pubspec.lock",
              "Package.resolved", "packages.lock.json", "flake.lock"}
_MANIFESTS = {"package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile",
              "Cargo.toml", "go.mod", "Gemfile", "composer.json", "mix.exs", "pubspec.yaml", "build.gradle",
              "build.gradle.kts", "pom.xml", "Package.swift", "deno.json", "pnpm-workspace.yaml", "lerna.json",
              "turbo.json", "nx.json"}
_TOOL_CONFIG = re.compile(
    r"(^|/)(Makefile|justfile|Taskfile\.ya?ml|\.tool-versions|\.nvmrc|\.node-version|\.python-version|"
    r"\.editorconfig|\.env\.example|\.env\.sample|\.envrc|tsconfig[^/]*\.json|jsconfig\.json|"
    r"\.?eslint[^/]*|\.?prettier[^/]*|biome\.json|ruff\.toml|\.ruff\.toml|\.flake8|mypy\.ini|\.pylintrc|"
    r"\.pre-commit-config\.yaml|\.husky/[^/]+|\.lintstagedrc[^/]*|lint-staged\.config\.[^/]+|"
    r"vite\.config\.[^/]+|webpack\.config\.[^/]+|rollup\.config\.[^/]+|babel\.config\.[^/]+|\.babelrc|"
    r"knip\.json|\.gitattributes|\.gitignore|\.dockerignore|devcontainer\.json|[^/]+\.(ini|cfg|conf|properties))$")
_CI = re.compile(r"(^|/)(\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.yml|\.circleci/|azure-pipelines\.yml|"
                 r"Jenkinsfile|\.buildkite/|bitbucket-pipelines\.yml|\.drone\.yml)")
_INFRA = re.compile(r"(^|/)(Dockerfile[^/]*|[^/]*\.Dockerfile|docker-compose[^/]*\.ya?ml|compose\.ya?ml|Procfile|"
                    r"fly\.toml|render\.yaml|vercel\.json|netlify\.toml|app\.yaml|serverless\.ya?ml|"
                    r"[^/]*\.tf|[^/]*\.tfvars|helm/|charts/|k8s/|kubernetes/|deploy/|infra/|ansible/|"
                    r"nginx[^/]*\.conf|Caddyfile)")
_TEST = re.compile(r"(^|/)(tests?|__tests__|spec|e2e|cypress|playwright)/|(_test|\.test|\.spec|_spec)\.[^/]+$|"
                   r"(^|/)test_[^/]+\.py$|(^|/)conftest\.py$|(^|/)(jest|vitest|playwright|cypress|karma)\.config\.[^/]+$|"
                   r"(^|/)pytest\.ini$|(^|/)tox\.ini$")
_MIGRATION = re.compile(r"(^|/)(migrations?|alembic|db/migrate|prisma/migrations)/")
_SCHEMA = re.compile(r"(\.prisma$|\.sql$|(^|/)schema[^/]*\.(rb|sql|graphql|gql|json|ya?ml|py|ts)$|(^|/)models?(\.py|/)|"
                     r"(^|/)entities/|(^|/)(db|database)/)")
_API = re.compile(r"(openapi[^/]*\.(json|ya?ml)$|swagger[^/]*\.(json|ya?ml)$|\.proto$|\.graphql$|\.gql$|"
                  r"(^|/)(routes?|routers?|controllers?|handlers?|endpoints|api)(/|\.[a-z]+$)|"
                  r"(^|/)[^/]*(router|routes|controller|handler|views)\.[a-z]+$)")
_UI = re.compile(r"\.(css|scss|sass|less|styl|vue|svelte|astro|html)$|(^|/)(components?|screens?|pages|views|"
                 r"layouts?|ui|styles?|theme|design|stories)/|\.stories\.[^/]+$|(^|/)tailwind\.config\.[^/]+$|"
                 r"(^|/)\.storybook/")
_DECISIONS = re.compile(r"(^|/)(adr|adrs|decisions|architecture/decisions|docs/decisions)/|(^|/)CHANGELOG[^/]*$|"
                        r"(^|/)HISTORY[^/]*$|(^|/)\d{3,4}-[^/]+\.md$")
_ARCH_DOC = re.compile(r"(^|/)(ARCHITECTURE[^/]*|architecture/|docs/architecture|DESIGN\.md)", re.I)
_PRODUCT_DOC = re.compile(r"(^|/)(README[^/]*|PRD[^/]*|prd[^/]*\.md|product/|docs/product|ABOUT[^/]*|"
                          r"GLOSSARY[^/]*|CONTRIBUTING[^/]*)$|(^|/)docs/[^/]+\.(md|mdx|rst)$", re.I)
_REQUIREMENTS = re.compile(r"(^|/)(requirements/|specs?/|stories/|features/)[^/]+\.(md|mdx|rst|txt)$|\.feature$|"
                           r"(^|/)(prd|requirements|spec)[^/]*\.(md|mdx)$", re.I)
_NFR = re.compile(r"(^|/)(SECURITY[^/]*|PRIVACY[^/]*|ACCESSIBILITY[^/]*|SLO[^/]*|SLA[^/]*|PERFORMANCE[^/]*)$|"
                  r"(^|/)(bench|benchmarks?|perf|load-?tests?|k6)/|\.k6\.[jt]s$|(^|/)lighthouserc[^/]*$", re.I)
_OPS_DOC = re.compile(r"(^|/)(runbooks?|ops|operations|playbooks?)/|(^|/)(RUNBOOK|DEPLOY|RELEASE|OPERATIONS)[^/]*$", re.I)


@dataclass(frozen=True)
class PathFacts:
    """One tracked path: what it is, which domains it's evidence for, and whether it will be read."""

    path: str
    size: int
    blob: str  # git's object id: changes when the content does
    language: str | None
    kinds: tuple[str, ...]
    domains: tuple[str, ...]
    status: str  # pending (to read), excluded, unsupported, inaccessible
    reason: str | None = None


@dataclass
class Inventory:
    commit: str
    paths: list[PathFacts] = field(default_factory=list)
    policy_version: str = POLICY_VERSION


def classify(path: str, *, size: int, mode: str = "100644", head: bytes | None = None) -> PathFacts:
    """What `path` is, from its name, git mode, size, and (for a text check) its first bytes."""
    name = PurePosixPath(path).name
    ext = PurePosixPath(path).suffix.lower()
    kinds: set[str] = set()
    domains: set[str] = set()
    language = LANGUAGES.get(ext)
    status, reason = "pending", None

    if mode == "160000":
        return PathFacts(path, 0, "", None, ("submodule",), ("dependencies",), "inaccessible",
                         "A submodule: its contents are another repository and weren't inspected")
    if mode == "120000":
        return PathFacts(path, size, "", None, ("symlink",), (), "excluded", "A symbolic link: its target is listed on its own")

    if _VENDORED.search(path):
        kinds.add("vendored")
        status, reason = "excluded", "Vendored third-party code"
    elif _GENERATED_DIRS.search(path) or _GENERATED_FILES.search(path) or (head is not None and _generated_header(head)):
        kinds.add("generated")
        status, reason = "excluded", "Generated: its source is described instead"

    binary = ext in _BINARY_EXT or (head is not None and b"\0" in head[:SNIFF_BYTES])
    if binary:
        kinds.add("binary")
        if ext in _DESIGN_ASSET_EXT:
            kinds.add("asset")
            domains.add("design")
        if status == "pending":
            status, reason = "excluded", "Binary: listed, not read"
    elif ext in _DESIGN_ASSET_EXT:  # an SVG: text, but an asset
        kinds.add("asset")
        domains.add("design")
    if status == "pending" and size > MAX_TEXT_BYTES:
        status, reason = "excluded", f"Larger than {MAX_TEXT_BYTES // 1_000_000} MB: listed, not read"

    if name in _LOCKFILES:
        kinds.add("lockfile")
        domains.add("dependencies")
    if name in _MANIFESTS or (name.startswith("requirements") and name.endswith(".txt")):
        kinds.add("manifest")
        domains.update({"dependencies", "tooling"})
    if _TOOL_CONFIG.search(path):
        kinds.add("config")
        domains.add("tooling")
    if _CI.search(path):
        kinds.add("ci")
        domains.update({"delivery", "quality"})
    if _INFRA.search(path):
        kinds.add("infrastructure")
        domains.add("delivery")
    if _TEST.search(path):
        kinds.add("test")
        domains.add("quality")
    if _MIGRATION.search(path):
        kinds.add("migration")
        domains.add("data")
    if _SCHEMA.search(path):
        kinds.add("schema")
        domains.add("data")
    if _API.search(path):
        kinds.add("api")
        domains.add("apis")
    if _UI.search(path) and "asset" not in kinds:
        kinds.add("ui")
        domains.add("design")
    if _DECISIONS.search(path):
        kinds.add("decision")
        domains.add("decisions")
    if _ARCH_DOC.search(path):
        kinds.add("doc")
        domains.add("architecture")
    if _PRODUCT_DOC.search(path):
        kinds.add("doc")
        domains.add("product")
    if _REQUIREMENTS.search(path):
        kinds.add("doc")
        domains.add("functional")
    if _NFR.search(path):
        kinds.add("doc" if ext in (".md", ".mdx", ".rst", ".txt", "") else "benchmark")
        domains.add("non_functional")
    if _OPS_DOC.search(path):
        kinds.add("doc")
        domains.add("delivery")
    if (ext in (".md", ".mdx", ".rst", ".txt", ".adoc")) and "doc" not in kinds and "test" not in kinds:
        kinds.add("doc")
    source = language is not None and language not in ("Markdown", "reStructuredText", "YAML", "TOML", "JSON",
                                                        "CSS", "SCSS", "Less", "HTML")
    if source and not kinds & {"test", "migration", "generated", "vendored"}:
        kinds.add("source")
        domains.add("architecture")  # the code is what the system is, whatever else it shows
    if not kinds:
        kinds.add("other")
    # (Every text file can be read; "unsupported" is for formats a parser can't handle yet.)
    return PathFacts(path, size, "", language, tuple(sorted(kinds)), tuple(sorted(domains)), status, reason)


def _generated_header(head: bytes) -> bool:
    """A file that says it was generated, in its first lines."""
    first = head[:600].lower()
    return any(marker in first for marker in (b"@generated", b"do not edit", b"auto-generated", b"autogenerated",
                                               b"code generated by", b"this file was automatically generated"))


async def take_inventory(root: Path) -> Inventory:
    """Every path git tracks at the checkout's HEAD, classified (nothing in the repository is run)."""
    commit = (await git(root, "rev-parse", "HEAD")).strip()
    listing = await git(root, "ls-files", "-s", "-z", timeout=120)
    entries = [line for line in listing.split("\0") if line]
    sizes = await _sizes(root, [e.split()[1] for e in entries if not e.startswith("160000")])
    out = Inventory(commit)
    for entry in entries:
        meta, path = entry.split("\t", 1)
        mode, blob, _stage = meta.split()
        size = sizes.get(blob, 0)
        head = None
        if mode == "100644" or mode == "100755":
            head = _head(root / path)
        facts = classify(path, size=size, mode=mode, head=head)
        out.paths.append(PathFacts(facts.path, facts.size, blob if mode != "160000" else "", facts.language,
                                   facts.kinds, facts.domains, facts.status, facts.reason))
    return out


async def _sizes(root: Path, blobs: Iterable[str]) -> dict[str, int]:
    """Each blob's size, in one `git cat-file --batch-check` (no file is read)."""
    import asyncio
    import subprocess

    wanted = "\n".join(dict.fromkeys(blobs)) + "\n"

    def run() -> str:
        done = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check=%(objectname) %(objectsize)"],
                              input=wanted, capture_output=True, text=True, timeout=120, check=False,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        return done.stdout

    sizes: dict[str, int] = {}
    for line in (await asyncio.to_thread(run)).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            sizes[parts[0]] = int(parts[1])
    return sizes


def _head(path: Path) -> bytes | None:
    try:
        with path.open("rb") as handle:
            return handle.read(SNIFF_BYTES)
    except OSError:
        return None
