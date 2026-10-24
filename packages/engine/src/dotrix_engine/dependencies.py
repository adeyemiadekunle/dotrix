"""A repository's dependencies from its manifests and lockfiles, without running anything.

Each manifest's direct dependencies (what it declares, and the scope: runtime, dev, optional,
peer), with the version its lockfile pins: the nearest lockfile of the same ecosystem in the
manifest's folder or above it (a workspace's root lockfile covers its packages). Formats read:
npm (package.json with package-lock.json, pnpm-lock.yaml, or yarn.lock), Python (pyproject.toml,
requirements*.txt, with uv.lock or poetry.lock), Cargo (Cargo.toml, Cargo.lock), and Go
(go.mod, which pins its own versions). Anything else is listed as not read yet, with why: the
repository's text is data, and a file that doesn't parse is reported, never guessed at.
"""
from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

MAX_BYTES = 30_000_000  # lockfiles run large (pnpm's, npm's); past this one is listed, not parsed

_NPM_SCOPES = (("dependencies", "runtime"), ("devDependencies", "dev"), ("optionalDependencies", "optional"),
               ("peerDependencies", "peer"))
_NPM_LOCKS = ("pnpm-lock.yaml", "package-lock.json", "yarn.lock")
_PY_LOCKS = ("uv.lock", "poetry.lock")
_REQUIREMENTS = re.compile(r"(^|/)requirements[^/]*\.txt$")
_PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


@dataclass(frozen=True)
class Dependency:
    ecosystem: str  # npm, pypi, cargo, go
    name: str
    declared: str | None  # what the manifest asks for (a range, a pin, a path)
    locked: str | None  # what the lockfile resolved it to (None: no lockfile, or it isn't in it)
    scope: str  # runtime, dev, optional, peer
    manifest: str
    lockfile: str | None


@dataclass
class Dependencies:
    dependencies: list[Dependency] = field(default_factory=list)
    unread: list[tuple[str, str]] = field(default_factory=list)  # (path, why it wasn't read)


def read_dependencies(root: Path, paths: Iterable[str]) -> Dependencies:
    """The direct dependencies the manifests among `paths` (tracked paths) declare."""
    tracked = set(paths)
    out = Dependencies()
    locks: dict[str, dict[str, object]] = {}  # lockfile path -> parsed (lazily)

    def lock_for(manifest: str, names: tuple[str, ...]) -> str | None:
        folder = PurePosixPath(manifest).parent
        while True:
            for name in names:
                candidate = str(folder / name) if str(folder) != "." else name
                if candidate in tracked:
                    return candidate
            if str(folder) == ".":
                return None
            folder = folder.parent

    def parsed(lock: str) -> dict[str, object] | None:
        if lock not in locks:
            try:
                locks[lock] = _parse_lock(root, lock)
            except _Unread as why:
                out.unread.append((lock, str(why)))
                locks[lock] = {}
        return locks[lock] or None

    for path in sorted(tracked):
        name = PurePosixPath(path).name
        try:
            if name == "package.json":
                lock = lock_for(path, _NPM_LOCKS)
                out.dependencies += _npm(root, path, lock, parsed(lock) if lock else None)
            elif name == "pyproject.toml" or _REQUIREMENTS.search(path):
                lock = lock_for(path, _PY_LOCKS)
                out.dependencies += _python(root, path, lock, parsed(lock) if lock else None)
            elif name == "Cargo.toml":
                lock = lock_for(path, ("Cargo.lock",))
                out.dependencies += _cargo(root, path, lock, parsed(lock) if lock else None)
            elif name == "go.mod":
                out.dependencies += _go(root, path)
            elif name in ("Gemfile", "composer.json", "mix.exs", "pubspec.yaml", "build.gradle", "build.gradle.kts",
                          "pom.xml", "Package.swift", "Pipfile", "setup.py", "setup.cfg", "deno.json"):
                out.unread.append((path, "No reader for this manifest yet"))
        except _Unread as why:
            out.unread.append((path, str(why)))
    return out


class _Unread(Exception):
    """A file that couldn't be read; the message says why (safe to show)."""


def _text(root: Path, path: str) -> str:
    file = (root / path).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        raise _Unread("Not in the checkout")
    if file.stat().st_size > MAX_BYTES:
        raise _Unread(f"Larger than {MAX_BYTES // 1_000_000} MB: listed, not parsed")
    try:
        return file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise _Unread("Not UTF-8 text") from exc


def _parse_lock(root: Path, path: str) -> dict[str, object]:
    """name -> version (npm, Python, Cargo); pnpm also keyed by importer folder."""
    name = PurePosixPath(path).name
    text = _text(root, path)
    try:
        if name == "pnpm-lock.yaml":
            data = yaml.safe_load(text) or {}
            importers = data.get("importers") or {".": {k: data.get(k) for k in ("dependencies", "devDependencies",
                                                                                   "optionalDependencies")}}
            return {"importers": {folder: _pnpm_importer(entry or {}) for folder, entry in importers.items()}}
        if name == "package-lock.json":
            data = json.loads(text)
            packages = data.get("packages") or {}
            versions = {k.rsplit("node_modules/", 1)[1]: v.get("version") for k, v in packages.items()
                        if k.startswith("node_modules/") and "/node_modules/" not in k and isinstance(v, dict)}
            versions |= {k: v.get("version") for k, v in (data.get("dependencies") or {}).items()
                         if isinstance(v, dict) and k not in versions}  # lockfile v1
            return {"versions": versions}
        if name == "yarn.lock":
            return {"specs": _yarn(text)}
        data = tomllib.loads(text)  # uv.lock, poetry.lock, Cargo.lock: [[package]] name, version
        norm = _pep503 if name in _PY_LOCKS else str
        return {"versions": {norm(p["name"]): p.get("version") for p in data.get("package", []) if "name" in p}}
    except (yaml.YAMLError, json.JSONDecodeError, tomllib.TOMLDecodeError, AttributeError, TypeError) as exc:
        raise _Unread(f"Couldn't parse it: {type(exc).__name__}") from exc


def _pnpm_importer(entry: dict) -> dict[str, str]:
    versions: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        for dep, value in (entry.get(key) or {}).items():
            version = value.get("version") if isinstance(value, dict) else value
            if isinstance(version, str):
                versions[dep] = version.split("(", 1)[0]  # "1.2.3(react@18.3.1)": the peers it resolved with
    return versions


def _yarn(text: str) -> dict[str, str]:
    """`"name@range"` -> version, for yarn 1 (`version "1.2.3"`) and berry (`version: 1.2.3`)."""
    specs: dict[str, str] = {}
    current: list[str] = []
    for line in text.splitlines():
        if line and not line.startswith((" ", "#")) and line.rstrip().endswith(":"):
            current = [s.strip().strip('"') for s in line.rstrip()[:-1].split(",")]
        elif current and (m := re.match(r'\s+version:?\s+"?([^"\s]+)"?', line)):
            for spec in current:
                specs[spec.replace("@npm:", "@")] = m.group(1)
            current = []
    return specs


def _npm(root: Path, path: str, lock: str | None, parsed: dict | None) -> list[Dependency]:
    try:
        data = json.loads(_text(root, path))
    except json.JSONDecodeError as exc:
        raise _Unread(f"Couldn't parse it: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise _Unread("Not a JSON object")
    folder = str(PurePosixPath(path).parent)
    if parsed and "importers" in parsed:  # pnpm: the importer is the manifest's folder, from the lockfile's
        base = str(PurePosixPath(lock).parent) if lock else "."
        rel = folder if base == "." else "." if folder == base else str(PurePosixPath(folder).relative_to(base))
        versions = parsed["importers"].get(rel, {})  # type: ignore[index, union-attr]
    else:
        versions = (parsed or {}).get("versions", {})  # type: ignore[assignment]
    specs = (parsed or {}).get("specs", {})
    found = []
    for key, scope in _NPM_SCOPES:
        for name, declared in (data.get(key) or {}).items():
            locked = versions.get(name) if isinstance(versions, dict) else None  # type: ignore[union-attr]
            if locked is None and isinstance(specs, dict):
                locked = specs.get(f"{name}@{declared}")
            found.append(Dependency("npm", name, str(declared), locked, scope, path, lock if locked else None))
    return found


def _pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _python(root: Path, path: str, lock: str | None, parsed: dict | None) -> list[Dependency]:
    text = _text(root, path)
    declared: list[tuple[str, str, str]] = []  # (requirement, scope, raw)
    if path.endswith(".txt"):
        scope = "dev" if re.search(r"dev|test|lint", PurePosixPath(path).name) else "runtime"
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith(("-", "git+", "http")):
                declared.append((line, scope, line))
    else:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise _Unread(f"Couldn't parse it: {exc}") from exc
        project = data.get("project") or {}
        declared += [(r, "runtime", r) for r in project.get("dependencies") or []]
        for extra in (project.get("optional-dependencies") or {}).values():
            declared += [(r, "optional", r) for r in extra]
        for group in (data.get("dependency-groups") or {}).values():
            declared += [(r, "dev", r) for r in group if isinstance(r, str)]
        poetry = (data.get("tool") or {}).get("poetry") or {}
        tables = [(poetry.get("dependencies") or {}, "runtime"), (poetry.get("dev-dependencies") or {}, "dev")]
        tables += [((g or {}).get("dependencies") or {}, "dev") for g in (poetry.get("group") or {}).values()]
        for table, scope in tables:
            for name, spec in table.items():
                if name.lower() != "python":
                    version = spec.get("version") if isinstance(spec, dict) else spec
                    declared.append((f"{name}{'' if version in (None, '*') else ' ' + str(version)}", scope, name))
    versions = (parsed or {}).get("versions", {})
    found = []
    for requirement, scope, _raw in declared:
        m = _PEP508.match(requirement.split(";", 1)[0])
        if not m:
            continue
        name, spec = m.group(1), m.group(3).strip() or None
        locked = versions.get(_pep503(name)) if isinstance(versions, dict) else None
        if locked is None and spec and spec.startswith("=="):
            locked = spec[2:].strip()
        found.append(Dependency("pypi", name, spec, locked, scope, path, lock if locked and lock else None))
    return found


def _cargo(root: Path, path: str, lock: str | None, parsed: dict | None) -> list[Dependency]:
    try:
        data = tomllib.loads(_text(root, path))
    except tomllib.TOMLDecodeError as exc:
        raise _Unread(f"Couldn't parse it: {exc}") from exc
    versions = (parsed or {}).get("versions", {})
    found = []
    for key, scope in (("dependencies", "runtime"), ("dev-dependencies", "dev"), ("build-dependencies", "dev")):
        for name, spec in (data.get(key) or {}).items():
            declared = spec.get("version") or spec.get("path") or spec.get("git") if isinstance(spec, dict) else spec
            crate = spec.get("package", name) if isinstance(spec, dict) else name
            locked = versions.get(crate) if isinstance(versions, dict) else None
            found.append(Dependency("cargo", name, str(declared) if declared else None, locked, scope, path,
                                    lock if locked else None))
    return found


def _go(root: Path, path: str) -> list[Dependency]:
    found, block = [], False
    for raw in _text(root, path).splitlines():
        line = raw.split("//", 1)[0].strip()
        indirect = "// indirect" in raw
        if line.startswith("require ("):
            block = True
            continue
        if block and line == ")":
            block = False
            continue
        entry = line.removeprefix("require ").strip() if (block or line.startswith("require ")) else ""
        parts = entry.split()
        if len(parts) >= 2 and not indirect:
            found.append(Dependency("go", parts[0], parts[1], parts[1], "runtime", path, path))
    return found
