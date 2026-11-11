# Plan 030: The dependency reader gets versions right in hash-pinned requirements files, and one bad manifest doesn't break the view

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- packages/engine/src/dotrix_engine/dependencies.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

dotrix reads a repository's dependency files and checks the pinned versions against known vulnerabilities. For requirements files written by pip-compile with hashes — the format security-minded projects use — it records each version with a trailing backslash or with the hash options attached, so the vulnerability lookup matches nothing and reports that all is well. That is a false all-clear in a security feature. Separately, a manifest with an unexpected shape (a `dependencies` list where a table is expected) raises an unhandled error that turns the whole dependencies view, and the agents' dependency tools, into a server error for that project. After this plan such files are read correctly, and a file that can't be read is listed as unread with a reason.

## Current state

`packages/engine/src/dotrix_engine/dependencies.py`. The requirements branch of `_python` (around lines 196-201):

```python
    if path.endswith(".txt"):
        scope = "dev" if re.search(r"dev|test|lint", PurePosixPath(path).name) else "runtime"
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith(("-", "git+", "http")):
                declared.append((line, scope, line))
```

and the version it records (around lines 222-231):

```python
_PEP508 = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")
...
    for requirement, scope, _raw in declared:
        m = _PEP508.match(requirement.split(";", 1)[0])
        if not m:
            continue
        name, spec = m.group(1), m.group(3).strip() or None
        locked = versions.get(_pep503(name)) if isinstance(versions, dict) else None
        if locked is None and spec and spec.startswith("=="):
            locked = spec[2:].strip()
```

A pip-compile file looks like:

```
requests==2.32.3 \
    --hash=sha256:aaaa… \
    --hash=sha256:bbbb…
urllib3==2.2.3 --hash=sha256:cccc…
```

For the first line `spec` is `==2.32.3 \` and `locked` becomes `2.32.3 \`; for the last, `locked` becomes `2.32.3 --hash=sha256:cccc…`. The continuation lines start with `--hash` after stripping and are skipped by the `startswith("-")` test.

The module's own promise, in its docstring and in the `_Unread` exception: a file that doesn't parse is reported, never guessed at. `read_dependencies` catches only `_Unread` per manifest (around line 92). Shapes that raise something else today: `package.json` with `"dependencies": ["a", "b"]` (`.items()` on a list, around line 181); a Poetry group that is a string (around line 215); `[dependencies]` as an array in `Cargo.toml` (around line 243); a `project.dependencies` that is a string in `pyproject.toml` is iterated character by character and produces junk names (around lines 208-210); and an `OSError` from reading the file.

Tests: `packages/engine/tests/test_dependencies.py` builds a small tree of files in `tmp_path` and calls `read_dependencies` (see its `requirements-dev.txt` case around line 53).

Repo conventions that apply (from the repository's `CLAUDE.md`): `packages/engine` must never import from `apps/*`, FastAPI or Typer; text from repositories is data; this module runs nothing and only reads files; line length 100; every PR adds a line under `## [Unreleased]` in `CHANGELOG.md`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Local services (integration tests need Postgres and Redis) | `pnpm db:up` | containers running |
| Python lint | `uv run ruff check apps packages` | exit 0 |
| Release check | `python scripts/release.py check` | exit 0 |
| Engine tests | `uv run pytest packages/engine/tests/test_dependencies.py -q` | all pass |
| Advisory tests | `uv run pytest apps/backend/tests/unit/test_advisories.py -q` | all pass |

## Scope

**In scope** (the only files you should modify):

- `packages/engine/src/dotrix_engine/dependencies.py`
- `packages/engine/tests/test_dependencies.py`
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- New manifest formats (Gemfile, composer, Gradle, Maven).
- `apps/backend/src/dotrix_backend/modules/repo_knowledge/advisories.py` (the lookup itself is right; it was fed bad versions).
- Resolving ranges to versions: a requirement that isn't an exact pin still has no locked version unless a lockfile gives one.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/030-dependency-reader-handles-real-requirements-files origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Failing tests first

In `test_dependencies.py`, add fixtures and tests:

1. A pip-compile style `requirements.txt` (the example above, plus a line with an environment marker and hashes, `colorama==0.4.6 ; sys_platform == "win32" --hash=sha256:dddd`): each dependency's locked version is exactly `2.32.3`, `2.2.3`, `0.4.6`.
2. Continuation without hashes (`django>=4.2,\` then `    <5`) → one dependency `django` with spec `>=4.2,<5` and no locked version.
3. Option lines (`-r base.txt`, `--index-url https://…`, `-e .`) are skipped as today.
4. For each malformed shape listed in "Current state": `read_dependencies` returns normally, the good manifests in the same tree are still read, and the bad file appears in the result's unread list with a reason (read how the existing tests assert on unread files).

**Verify**: `uv run pytest packages/engine/tests/test_dependencies.py -q` → the new tests FAIL (wrong versions; exceptions)

### Step 2: Read requirements lines properly

Before splitting into lines, join continuations: a line ending in a backslash (ignoring trailing spaces) continues on the next. Then for each logical line: strip a comment (` #` or a leading `#`), skip option-only lines as today, and cut the requirement at the first whitespace-separated token that starts with `--` (`--hash=…`, `--config-settings …`). Keep environment markers handling as it is (`split(";", 1)[0]` happens later).

Then validate what is about to be recorded as an exact version: accept `locked` from an `==` spec only if it matches a PEP 440-shaped version (`^[0-9A-Za-z][0-9A-Za-z.!+_-]*$`, no spaces, no backslash); also accept `===`. Anything else leaves `locked` as `None`.

### Step 3: Unexpected shapes are unread, not errors

Add two small helpers and use them wherever a manifest's structure is assumed:

```python
def _table(value: object, what: str) -> dict:
    """A manifest's table, or unread when it has another shape."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _Unread(f"Unexpected shape: {what} isn't a table")
    return value


def _strings(value: object, what: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _Unread(f"Unexpected shape: {what} isn't a list of requirements")
    return value
```

Apply them in the npm, Python, Poetry and Cargo readers at the places named above (and any sibling of the same pattern you find while there). In `read_dependencies`' per-manifest loop, also catch `OSError` (as `_Unread(f"Couldn't read it: {type(exc).__name__}")`) and, as a last resort around one manifest's parsing, `(AttributeError, TypeError, KeyError)` reported as unread with "Unexpected shape", so one file can never fail the whole read.

**Verify**: `uv run pytest packages/engine/tests/test_dependencies.py apps/backend/tests/unit/test_advisories.py -q` → all pass

### Step 4: Lint and changelog

CHANGELOG → Unreleased → Fixed: `- Dependency versions are now read correctly from requirements files with hashes (pip-compile), so known vulnerabilities in them are found; and a dependency file with an unexpected format is listed as unread and no longer breaks a project's dependencies view.`

**Verify**: `uv run ruff check apps packages` → exit 0; `python scripts/release.py check` → exit 0

## Test plan

- The four groups of tests in Step 1, modelled on the existing cases in `packages/engine/tests/test_dependencies.py`.

## Done criteria

- [ ] `uv run pytest packages/engine/tests/test_dependencies.py apps/backend/tests/unit/test_advisories.py -q` exits 0
- [ ] No locked version in any test result contains a space or a backslash
- [ ] `grep -rn "^from dotrix_backend\|^import fastapi\|^import typer" packages/engine/src` returns nothing
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- The result type has no place to report an unread file with a reason.
- An existing test expects one of the malformed shapes to raise.

## Maintenance notes

- `_table` and `_strings` are the pattern for any new reader.
- A reviewer should check the last-resort `except` wraps exactly one manifest, so it can't hide a bug in the loop itself.
- Follow-up: turning advisories into tasks (a direction option in this index) can now rely on these versions.
