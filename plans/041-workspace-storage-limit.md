# Plan 041: Each workspace has a storage limit for uploads, shown in Settings and enforced on upload

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- apps/backend/src/dotrix_backend/modules/documents apps/backend/src/dotrix_backend/modules/issues/service.py apps/backend/src/dotrix_backend/modules/issues/router.py apps/backend/src/dotrix_backend/modules/workspaces apps/backend/src/dotrix_backend/core/settings.py apps/backend/src/dotrix_backend/modules/admin`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: none
- **Category**: feature
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

Today a single upload is capped (`DOTRIX_MAX_UPLOAD_MB`, 25 MB), but nothing
caps how much a workspace stores in total. Anyone with an account can fill the
deployment's object storage with documents and task attachments. With personal
workspaces launching first and no billing, a per-workspace limit is the control
that keeps one account from using the disk everyone shares, and it is the
hook a paid plan would later raise.

After this plan:

- every workspace has a limit on what its people upload (document originals and
  task attachments), with a deployment default and an optional per-workspace
  override the operator sets in the admin console;
- an upload that would pass the limit is refused with a clear message;
- Settings shows how much is used, and owners see it before it's full.

**Design decisions (made here; change them in review, not mid-execution):**

1. **What counts:** uploaded document originals and task attachments. Both
   already record `size`. Not counted in this version: knowledge files'
   Markdown and their version history (rows in Postgres, small), coding
   screenshots, saved coding sessions, profile photos. They are system-made or
   tiny, and counting them would make a person's limit move without them
   uploading anything.
2. **Usage is computed, not stored:** `SUM(size)` over the two tables for the
   workspace. No counter column to drift out of step on deletes, moves or
   failed uploads. Both tables are indexed by project; if the query needs it,
   Step 1 adds an index.
3. **The limit:** `DOTRIX_WORKSPACE_STORAGE_MB` (default `1024`, i.e. 1 GB;
   `0` means unlimited, which is also the default in development and tests so
   nothing existing breaks). A nullable `workspaces.storage_limit_mb` overrides
   it for one workspace (`0` = unlimited for that workspace).
4. **Over the limit:** uploads are refused; nothing is deleted, and reading,
   downloading and deleting always work. A workspace already over a newly
   lowered limit simply can't add more.
5. **Races:** two uploads at once can each pass the check and together exceed
   the limit by at most one upload's size. That is accepted; no lock is taken.

## Current state

- `apps/backend/src/dotrix_backend/core/settings.py:197`: `max_upload_mb: int = Field(default=25, ge=1, le=200)`.
- Documents: `apps/backend/src/dotrix_backend/modules/documents/router.py:46` reads `limit = settings.max_upload_mb * 1_000_000`; `apps/backend/src/dotrix_backend/modules/documents/service.py` (~lines 90-103):

```python
        if len(data) > max_bytes:
            raise UploadTooLarge(f"Uploads are limited to {max_bytes // 1_000_000} MB")
        ...
        storage_key = f"{project.workspace_id}/{project.id}/{document_id}/{filename}"
        await self.storage.put(storage_key, data, content_type)
```

  `Document` (`documents/models.py`) has `project_id`, `size: Mapped[int]`, `storage_key`. Check whether it has `workspace_id` (the `WorkspaceScoped` mixin); if not, join through `projects`. Duplicating a document (`documents/service.py`, "duplicate") stores a second copy: it must pass the same check.
- Attachments: `apps/backend/src/dotrix_backend/modules/issues/router.py:268-282` (`attach_file_to_issue`) and `apps/backend/src/dotrix_backend/modules/issues/service.py:~831` (`attach`, `storage.put`). `IssueAttachment` (`issues/models.py:~201`) has `size: Mapped[int]`.
- `Workspace` (`apps/backend/src/dotrix_backend/modules/workspaces/models.py:~35-54`) has settings columns such as `approval_mode_cap: Mapped[str | None]`; add the new column beside them.
- Errors: domain exceptions map once in `core/errors.py`; `UploadTooLarge` exists (find its status with `grep -n UploadTooLarge -r apps/backend/src`).
- Admin console: `apps/backend/src/dotrix_backend/modules/admin/platform.py:349` `workspaces(...)` lists workspaces with usage (`WorkspaceUsage`); the console's own routes live in `apps/backend/src/dotrix_backend/modules/admin`.
- Moving a project between workspaces (`workspaces` module, "explicit project moves") carries its documents and attachments to the destination.
- Web: Settings reads and saves through `apps/web/src/data/account.ts` (`useApi`, each save naming the query kinds it changes: `WORKSPACE`, ...). Upload errors surface as toasts from the API's problem detail.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `uv run pytest apps/backend/tests/integration/test_workspace_storage.py apps/backend/tests/integration/test_isolation.py -q` | pass |
| Migration | `pnpm db:revision "workspace storage limit" && uv run alembic -c apps/backend/alembic.ini check` | No new upgrade operations |
| API client | `pnpm openapi` | regenerated, committed |
| Web | `pnpm build && pnpm typecheck && pnpm test && pnpm knip` | pass |
| Lint and format | `uv run ruff check apps packages && pnpm lint && pnpm format:check` | clean |
| Release check | `python scripts/release.py check` | exit 0 |

Integration tests need Postgres and Redis (`pnpm db:up`) and the `DOTRIX_*` test variables described in `CLAUDE.md`.

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/workspaces/` (model, a small `storage.py` service, schemas, router)
- `apps/backend/src/dotrix_backend/modules/documents/service.py`, `apps/backend/src/dotrix_backend/modules/issues/service.py` (the two upload paths and document duplication)
- `apps/backend/src/dotrix_backend/core/settings.py`, `core/errors.py`
- `apps/backend/src/dotrix_backend/modules/admin/` (show usage and set a workspace's limit)
- one Alembic migration
- `apps/web/src/screens/Settings*` and `apps/web/src/data/account.ts` (a usage line), `apps/admin/src` (the limit field)
- `packages/api-client` (generated), tests, `tests/integration/test_isolation.py`'s `World` if a new route takes an id
- `.env.example`, `deploy/README.md` (the new setting), `CLAUDE.md` (one paragraph)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- Billing, plans, or per-person limits.
- Counting or limiting knowledge versions, screenshots, saved sessions, photos.
- Deleting anything automatically.
- The per-file limit (`max_upload_mb`).

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: Usage and the limit, in one small service

`modules/workspaces/storage.py`:

- `async def used_bytes(session, workspace_id) -> int`: the sum of `Document.size` and `IssueAttachment.size` for the workspace (two scalar subqueries, each scoped by workspace, joining through `projects` where the table has no `workspace_id`).
- `def limit_bytes(workspace, settings) -> int | None`: the workspace's `storage_limit_mb` when set, else `settings.workspace_storage_mb`; `0` → `None` (unlimited).
- `async def ensure_room(session, workspace, settings, incoming: int) -> None`: raises `StorageFull` when a limit applies and `used + incoming > limit`. Message: `This workspace's storage is full ({used} of {limit} used). Delete files you no longer need, or ask for a higher limit.` with sizes formatted in MB/GB.
- `StorageFull` in `core/errors.py`, mapped to **413** with problem type `storage_full` (so the web can tell it from a too-large single file).

Add `workspace_storage_mb: int = Field(default=1024, ge=0)` to settings, defaulting to `0` when the environment is development or test, the way `organisations_enabled` picks its default by environment (read how that one is done and follow it).

Add `storage_limit_mb: Mapped[int | None]` to `Workspace`; migration with `pnpm db:revision "workspace storage limit"`.

**Verify**: `alembic check` clean; a unit or integration test of the three functions passes.

### Step 2: Enforce on every path that stores an upload

Call `ensure_room(..., incoming=len(data))` before `storage.put` in: document upload, document duplicate, task attachment. Find any other path that writes a person's file with `grep -rn "storage.put(" apps/backend/src` and list each in your report as counted or deliberately not (per decision 1).

Moving a project into a workspace: check the destination has room for the project's counted bytes, and refuse the move with the same error if not.

### Step 3: Read it

- `GET /v1/workspaces/{workspace_id}/storage` → `{ used_bytes, limit_bytes | null, documents_bytes, attachments_bytes }`, for any member (a personal workspace's owner; in an organisation, members see it, and it isn't sensitive). Docstring, `responses=errors(...)`, and a row in `test_isolation.py`.
- Admin: add `used_bytes` and `storage_limit_mb` to the console's workspace list, and a route to set or clear a workspace's `storage_limit_mb` (admin only, audited as `workspace.storage_limit_updated` in the audit log with old and new values). If plans 011-018 have changed the admin module's shape, follow what is there.
- `pnpm openapi`.

### Step 4: Show it

- Web, Settings → the workspace's general section: one line, `Storage: 312 MB of 1 GB used`, with a thin bar using the design's tokens (no raw colours), turning to the warning tone at 80% and the danger tone at 100% with `Uploads are paused until you delete files or the limit is raised.` When there's no limit, show only what's used. The seeded workspace shows a sample figure marked as sample data, like its other sample content.
- A refused upload's toast shows the API's message. Check both upload surfaces (Files and a task's attachments) show it and don't leave a phantom row.
- Admin console: the limit field on a workspace, and usage in the workspaces table.

### Step 5: Docs and changelog

`.env.example` and `deploy/README.md`: `DOTRIX_WORKSPACE_STORAGE_MB` with its default and `0`. `CLAUDE.md`: a short paragraph under the workspace sections saying what counts, where it's enforced and where the override lives. Under Unreleased → Added: `- Each workspace has a storage limit for uploaded documents and task attachments (1 GB by default; the operator can change it per workspace). Settings shows how much is used, and an upload that doesn't fit is refused with the reason.`

## Test plan

Integration (one file, `tests/integration/test_workspace_storage.py`), with the limit set through settings overrides in the test:

1. Under the limit: a document upload and an attachment succeed; `GET .../storage` reports their sizes split by kind.
2. An upload that would pass the limit is refused with 413 and type `storage_full`; nothing is stored (the fake storage has no new key) and no row exists.
3. After deleting a document, the same upload succeeds (usage is computed).
4. Document duplicate is refused when it wouldn't fit.
5. `storage_limit_mb` on the workspace overrides the setting, both ways (higher allows, lower refuses); `0` is unlimited.
6. With the setting at `0` and no override, nothing is refused.
7. A workspace over a lowered limit can still download and delete.
8. Moving a project into a full workspace is refused; into one with room succeeds.
9. Another workspace's uploads don't count (isolation), and the new route is covered by `test_isolation.py`.
10. Admin: setting the limit is audited; a non-admin can't.

Web unit test for the formatter (`312 MB of 1 GB`, the 80% and 100% states, no limit).

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] All ten integration tests and the web unit test pass
- [ ] `grep -rn 'storage.put(' apps/backend/src` — every hit is listed in the report as counted or not
- [ ] `alembic check` clean; `pnpm openapi` leaves no diff; `uv run pytest apps/backend/tests/integration/test_isolation.py -q` passes
- [ ] `pnpm build && pnpm typecheck && pnpm test && pnpm knip` pass; ruff, `pnpm lint`, `pnpm format:check`, `python scripts/release.py check` clean
- [ ] The existing suite passes with the default (unlimited in tests)
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- `Document` or `IssueAttachment` can't be scoped to a workspace with an indexed query.
- The admin module has changed shape (plans 011-018 in progress) so that Step 3's admin route has no obvious home: ship Steps 1-2, the member-facing read and the web line, and report the admin part as not done.
- An upload path stores bytes without a row carrying their size.
- Changing the default would refuse uploads in an existing deployment whose workspaces already exceed 1 GB: report the largest workspace's usage query for the owner to run before deploying.

## Maintenance notes

- (owner) Before deploying, check current usage (`select workspace, sum(size) ...`) so no existing workspace is surprised; set `DOTRIX_WORKSPACE_STORAGE_MB` or per-workspace overrides accordingly.
- When billing exists, a plan sets `storage_limit_mb`; nothing else needs to change.
- If system-made files (screenshots, saved sessions) grow large, cap them with their own retention, not this limit.
- An email or Inbox notice to owners at 80% and 100% is a natural follow-up; it was left out to keep this plan to one change.
