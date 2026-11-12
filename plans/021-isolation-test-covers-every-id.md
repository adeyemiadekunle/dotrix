# Plan 021: The cross-workspace test tries every kind of ID, not eight of them

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/tests/integration/test_isolation.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (test only; it may expose a real leak)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

The most important security property of the API is that an ID from someone else's workspace never works in yours. One test checks it for every route by substituting another person's IDs into the caller's own workspace paths. But it substitutes only eight ID names. Coding runs, coding sessions, runners, automations, lessons, approvals, chat inputs, outputs and issue keys are never tried, and those cover the product's highest-stakes actions (approving and pushing code). After this plan the test substitutes every ID a route takes, and fails if a new ID name appears that it doesn't know how to treat.

## Current state

`apps/backend/tests/integration/test_isolation.py`:

- `World` / `build_world(email, name)` creates one person's workspace with one of every resource and exposes `params`: a dict of path-parameter name → that person's value (`workspace_id`, `project_id`, `document_id`, `run_id`, `thread_id`, `coding_run_id`, `session_id`, `runner_id`, `automation_id`, `lesson_id`, `link_id`, `output_id`, `approval_id`, `input_id`, `key`, …; read lines ~150-325 for the full list).
- `_scoped_routes(db_client)` yields `(method, template, body)` for every route under a workspace.
- The test in question (around lines 340-375):

```python
    """Mallory owns her workspace, so she passes every permission check there; each of Ada's
    IDs, used under Mallory's workspace (and project), must still be not found."""
    ada = await build_world("ada@example.com", "Ada")
    mallory = await build_world("mallory@example.com", "Mallory")
    mixed_in = [
        "project_id",
        "document_id",
        "run_id",
        "thread_id",
        "invite_id",
        "user_id",
        "attachment_id",
        "comment_id",
    ]
    leaks = []
    for method, template, body in _scoped_routes(db_client):
```

Read the rest of the loop to see how a route is called with Mallory's params and one of Ada's substituted, and what counts as a leak (anything other than 404, with documented exceptions).

Repo conventions that apply (from the repository's `CLAUDE.md`): backend layering is router → service, routers never query; raise domain exceptions from `dotrix_backend.core.errors`; every query is scoped by workspace or project; services commit once per unit of work; line length 100; every PR adds a line under `## [Unreleased]` in `CHANGELOG.md`, written for people who use dotrix, in the existing section of the right kind.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Local services (integration tests need Postgres and Redis) | `pnpm db:up` | containers running |
| Python lint | `uv run ruff check apps packages` | exit 0 |
| Release check | `python scripts/release.py check` | exit 0 |
| The isolation tests | `uv run pytest apps/backend/tests/integration/test_isolation.py -q` | all pass |

## Scope

**In scope** (the only files you should modify):

- `apps/backend/tests/integration/test_isolation.py`

**Out of scope** (do NOT touch):

- Any file under `apps/backend/src`. If the widened test finds a leak, that is a finding to report, not something to fix in this plan (see STOP conditions).
- The other tests in the file.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/021-isolation-test-covers-every-id origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Derive the list instead of hand-writing it

Replace the literal `mixed_in` list with every path-parameter name that appears in `_scoped_routes` templates and exists in `ada.params`, minus the names that are not another tenant's identifiers:

```python
    NOT_AN_ID = {"workspace_id"}  # the caller's own workspace is the frame every route is tried in
    in_routes = {name for _, template, _ in _scoped_routes(db_client) for name in re.findall(r"{(\w+)}", template)}
    mixed_in = sorted((in_routes & set(ada.params)) - NOT_AN_ID)
```

Add to `NOT_AN_ID`, each with a one-line comment saying why, only names whose value is not a resource of the workspace (for example an enum-like segment such as a provider name, or a file path). Decide each by reading the route, not by whether the test passes.

### Step 2: Fail on an ID the test can't supply

Still in the test, assert that every parameter name used by a scoped route is known:

```python
    unknown = in_routes - set(ada.params) - NOT_AN_ID
    assert not unknown, f"routes take IDs the World doesn't build: {sorted(unknown)}"
```

If this fires for names that already exist today, add them to `World` when the resource is cheap to create with the helpers already in the file, or list them in a clearly named `NOT_BUILT = {...}` set with a comment per name saying what is missing — and say so in your report. Do not silently drop them.

### Step 3: Human keys

`key` (an issue key such as `KUN-1`) is the same string in both worlds when both projects use the same project key. Check how `build_world` names its project: if Ada's and Mallory's issue keys can be identical, substituting proves nothing. Give the two worlds different project keys (or different issue numbers) so that Ada's key does not exist in Mallory's project, and keep `key` in `mixed_in`.

### Step 4: Run it and read every failure

**Verify**: `uv run pytest apps/backend/tests/integration/test_isolation.py -q`

- All pass → done.
- A failure whose response is 404 for a different documented reason, or a route that legitimately validates its body before looking the resource up: the file has an existing mechanism for that (`BODIES`, and any documented exception set near the loop); use it, with a comment.
- A failure where the route answered with data or performed the action using Ada's ID from Mallory's workspace: STOP. That is a real cross-workspace leak. Report the method, the route template, the substituted parameter and the status code. Do not weaken the test, and do not fix the route under this plan.

## Test plan

- The changed test itself. To prove it bites: temporarily add a known-good name (for example `coding_run_id`) to `NOT_AN_ID`, confirm the count of substitutions drops (print `len(mixed_in)`), then remove it.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_isolation.py -q` exits 0
- [ ] `mixed_in` is derived, and contains at least `coding_run_id`, `session_id`, `runner_id`, `automation_id`, `approval_id` (print it once and paste it in your report)
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- The widened test finds a route that serves or acts on another workspace's resource (see Step 4).
- More than five parameter names end up in `NOT_BUILT`: the World needs real work; report the list.

## Maintenance notes

- A new resource now needs a row in `World` or the test fails at Step 2's assertion; that is the intended ratchet.
- A reviewer should read `NOT_AN_ID` and `NOT_BUILT` critically: every entry weakens the test.
