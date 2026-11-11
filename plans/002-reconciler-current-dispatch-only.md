# Plan 002: The coding reconciler only judges a run by its current dispatch

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- apps/backend/src/dotrix_backend/modules/execution/service.py`
> If the file changed since this plan was written, compare the "Current state"
> excerpt against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `f477722`, 2026-11-11

## Why this matters

In worker mode every coding run is dispatched through an outbox table,
`run_dispatches`. One coding run gets a **new dispatch row each time it is
queued again** (accepting its changes in Manual mode, a local turn's publish
pass, a recovery retry): `record_dispatch` increments
`run.dispatch_generation` and inserts a row with that generation. The older
rows stay, still marked accepted.

Once a minute the worker runs `reconcile_coding`, which looks for accepted
dispatches of RUNNING coding runs whose queue job is finished or gone, and
marks the run `recovery_required`. Its query does not restrict to the run's
**current** generation. So while a run is working under generation 2, the
finished job of generation 1 makes the sweep flag the live run as needing
recovery. The worker then stops writing for that run, leaving a push or pull
request half done until a person presses Recover. After this plan, only the
current, non-discarded dispatch can cause that.

## Current state

- `apps/backend/src/dotrix_backend/modules/execution/service.py` — the dispatch outbox. `record_dispatch` (lines 60-80), `accept_operation` (around lines 104-138), `RunDispatcher.reconcile_coding` (lines 329-375).
- `apps/backend/src/dotrix_backend/modules/execution/models.py` — `RunDispatch` (`generation`, `delivery_generation`, `accepted_at`, `discarded_at`, `coding_run_id`, `queue_name`, …).
- `apps/backend/src/dotrix_backend/modules/coding/models.py:124` — `CodingRun.dispatch_generation`.
- `apps/backend/src/dotrix_backend/worker.py:161-166, 212` — the cron that calls `reconcile_coding`.

`record_dispatch` (how generations are made), `service.py:60-80`:

```python
    run.dispatch_generation = (run.dispatch_generation or 0) + 1
    now = datetime.now(UTC)
    operation = RunDispatch(
        id=uuid7(), workspace_id=run.workspace_id,
        agent_run_id=run.id if isinstance(run, AgentRun) else None,
        coding_run_id=run.id if isinstance(run, CodingRun) else None,
        generation=run.dispatch_generation, queue_name=queue_name, payload=payload,
        created_at=now, next_attempt_at=now, publish_attempts=0,
    )
```

The candidate query today, `service.py:332-340`:

```python
        async with self.session_factory() as session:
            candidates = list((await session.execute(select(
                RunDispatch.workspace_id, RunDispatch.id, RunDispatch.coding_run_id,
                RunDispatch.delivery_generation,
            ).join(CodingRun, CodingRun.id == RunDispatch.coding_run_id).where(
                RunDispatch.queue_name == self.queue.queue_name,
                RunDispatch.coding_run_id.is_not(None), RunDispatch.accepted_at <= cutoff,
                CodingRun.status == CodingRunStatus.RUNNING,
            ).order_by(RunDispatch.accepted_at).limit(limit))).all())
```

The recheck under lock today, `service.py:364-375`:

```python
            async with self.session_factory() as session:
                run = await session.scalar(select(CodingRun).where(
                    CodingRun.workspace_id == workspace_id, CodingRun.id == run_id,
                ).with_for_update(skip_locked=True))
                if run is None or run.status is not CodingRunStatus.RUNNING:
                    continue
                operation = await session.scalar(select(RunDispatch).where(
                    RunDispatch.workspace_id == workspace_id, RunDispatch.id == dispatch_id,
                    RunDispatch.coding_run_id == run_id, RunDispatch.accepted_at.is_not(None),
                ).with_for_update(skip_locked=True))
                if operation is None or operation.delivery_generation != delivery_generation:
                    continue
                if mark_coding_recovery_required(session, run, reason=reason, source=f"arq:{status.value}"):
```

The pattern to copy already exists in the same file, in `accept_operation`
(`service.py:127-131`):

```python
    row = await session.scalar(select(RunDispatch).where(
        RunDispatch.workspace_id == run.workspace_id, RunDispatch.id == operation.id,
        target == run.id, RunDispatch.generation == run.dispatch_generation,
        RunDispatch.discarded_at.is_(None),
    ).with_for_update())
```

Note the two different columns: `generation` is which queueing of the run this
row is (compare with `CodingRun.dispatch_generation`); `delivery_generation` is
how many times this one row has been published to the queue (part of the arq
job id). Do not confuse them.

Conventions: every query is scoped by `workspace_id` (keep the existing
filters); line length 100; no behaviour change beyond the two filters.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Local services | `pnpm db:up` | Postgres and Redis running |
| New tests | `uv run pytest apps/backend/tests/integration/test_coding_reconcile.py -q` | all pass (skipped only if Redis is unreachable — see STOP conditions) |
| Related suites | `uv run pytest apps/backend/tests/integration/test_coding.py apps/backend/tests/integration/test_agent_worker.py apps/backend/tests/integration/test_worker_jobs.py -q` | all pass |
| Lint | `uv run ruff check apps packages` | exit 0 |

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/execution/service.py` (only `reconcile_coding`)
- `apps/backend/tests/integration/test_coding_reconcile.py` (create)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- `record_dispatch`, `accept_operation`, `sweep`, `publish`, `expire_agent_leases` — correct as they are.
- `modules/coding/runner.py`, `modules/coding/recovery.py`, `worker.py` — the fix is only which rows the reconciler inspects.
- Discarding or deleting old dispatch rows — a separate cleanup, not needed here.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/002-reconciler-current-dispatch origin/stage`. PRs go into `stage`, never `main`.
- Commit message: one short sentence-case line (e.g. `Coding reconciler: only the run's current dispatch can flag it`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write the failing test first

Create `apps/backend/tests/integration/test_coding_reconcile.py`. It needs the
`redis` fixture (defined in `apps/backend/tests/conftest.py:144`; it skips the
test when Redis is unreachable) and a database session.

Build the state directly in the database, the way
`apps/backend/tests/integration/test_admin.py` does with helpers from
`test_observe.py`:

- `from .test_observe import _coding_run` gives
  `_coding_run(ws: str, project: str, issue: str, ada, **kw) -> CodingRun`
  (keyword overrides such as `status=CodingRunStatus.RUNNING`,
  `dispatch_generation=2`).
- Create the workspace, project and issue through the API exactly as
  `test_admin.py::test_me_and_the_platform_reads` does (lines 41-52:
  `owner = await signup()`, list workspaces, `POST …/projects`, `POST …/issues`).
- Insert `RunDispatch` rows with `db_session.add(...)`. Required columns:
  `id=uuid7()` (import `uuid7` from wherever `execution/service.py` imports
  it), `workspace_id`, `coding_run_id`, `generation`, `queue_name`,
  `payload={}`, `created_at`, `next_attempt_at`, `publish_attempts=0`,
  `accepted_at`. Commit with `await db_session.commit()`.
- Use a unique queue name per test: `name = f"dotrix:test:{uuid.uuid4().hex[:8]}"`
  and `queue = RunQueue(redis, queue_name=name)` (`from dotrix_backend.modules.agents.queue import RunQueue`).
- The dispatcher: `RunDispatcher(factory, queue)` where `factory` is the app's
  session factory, obtained as `db_client._transport.app.state.runner.session_factory`
  (see `test_agent_worker.py:195-196`). Call `await RunDispatcher(factory, queue).reconcile_coding()`.

No job is ever enqueued in these tests, so arq reports every job as
`not_found` — exactly the "job is gone" case.

Tests:

1. `test_an_older_dispatch_does_not_flag_a_run_working_under_a_newer_one`:
   a RUNNING coding run with `dispatch_generation=2`; dispatch A
   (`generation=1`, `accepted_at` 10 minutes ago); dispatch B (`generation=2`,
   `accepted_at` = now, i.e. inside the 60-second grace so it is not a
   candidate). Expect `reconcile_coding()` to return `0` and the run's status
   to still be `CodingRunStatus.RUNNING` (re-read it in a fresh session from
   `factory()`).
2. `test_a_discarded_dispatch_does_not_flag_a_run`: a RUNNING run with
   `dispatch_generation=1`; its only dispatch has `generation=1`,
   `accepted_at` 10 minutes ago and `discarded_at` set. Expect `0`, still RUNNING.
3. `test_the_current_dispatch_whose_job_is_gone_still_flags_the_run`
   (characterization — must pass before and after the fix): a RUNNING run with
   `dispatch_generation=1`; one dispatch `generation=1`, `accepted_at` 10
   minutes ago, not discarded. Expect `reconcile_coding()` to return `1` and
   the run's status to be `CodingRunStatus.RECOVERY_REQUIRED`.

**Verify**: `uv run pytest apps/backend/tests/integration/test_coding_reconcile.py -q` → test 1 and test 2 FAIL (returns 1 / status recovery_required), test 3 passes. If tests 1 and 2 pass before any code change, STOP: the bug is not as described.

### Step 2: Restrict the candidate query

In `reconcile_coding`, add two conditions to the `.where(...)` of the candidate
query:

```python
                RunDispatch.generation == CodingRun.dispatch_generation,
                RunDispatch.discarded_at.is_(None),
```

### Step 3: Recheck the generation under the lock

In the same method, add the same two conditions to the locked `operation`
lookup, using the locked `run`:

```python
                operation = await session.scalar(select(RunDispatch).where(
                    RunDispatch.workspace_id == workspace_id, RunDispatch.id == dispatch_id,
                    RunDispatch.coding_run_id == run_id, RunDispatch.accepted_at.is_not(None),
                    RunDispatch.generation == run.dispatch_generation,
                    RunDispatch.discarded_at.is_(None),
                ).with_for_update(skip_locked=True))
```

Leave the `delivery_generation` comparison on the next line as it is.

**Verify**: `uv run pytest apps/backend/tests/integration/test_coding_reconcile.py -q` → 3 passed

### Step 4: Run the related suites and lint

**Verify**:
- `uv run pytest apps/backend/tests/integration/test_coding.py apps/backend/tests/integration/test_agent_worker.py apps/backend/tests/integration/test_worker_jobs.py -q` → all pass
- `uv run ruff check apps packages` → exit 0

### Step 5: Changelog

Under `## [Unreleased]` in `CHANGELOG.md`, in a `### Fixed` section (create it
if missing), add:
`- A coding turn that was queued more than once (accepting its changes, a recovery retry) is no longer marked as needing recovery while it is still working.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New file `apps/backend/tests/integration/test_coding_reconcile.py` with the three tests in Step 1.
- Structural patterns: `test_agent_worker.py::test_a_run_whose_worker_stopped_goes_on_in_another` (dispatcher + queue + direct DB updates) and `test_admin.py` (inserting `CodingRun` rows via `_coding_run`).
- Verification: `uv run pytest apps/backend/tests/integration/test_coding_reconcile.py -q` → 3 passed.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_coding_reconcile.py -q` → 3 passed (not skipped)
- [ ] The three related suites in Step 4 pass
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `grep -n "RunDispatch.generation == " apps/backend/src/dotrix_backend/modules/execution/service.py` shows the two new lines inside `reconcile_coding`
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- The excerpts in "Current state" do not match the live code.
- The new tests are **skipped** because Redis is unreachable: do not mark the plan done on skipped tests; report that Redis is needed (`pnpm db:up`, or `DOTRIX_TEST_REDIS_URL`).
- Tests 1 and 2 pass before the code change (the bug is not reproducible as described).
- `CodingRun` cannot be inserted with `_coding_run` because required columns changed — report which column, do not guess values for unfamiliar fields beyond simple defaults.
- Any existing test in the Step 4 suites fails after the change.

## Maintenance notes

- If dispatch rows are ever pruned or a run's older dispatches are marked `discarded_at` when a new one is recorded, the `generation` filter stays correct and the `discarded_at` filter becomes the main guard.
- A reviewer should confirm no other sweep in this file joins dispatches to runs without the generation filter (at planning time: `sweep`/`publish` handle unaccepted rows and already compare generations; `expire_agent_leases` filters by `RunDispatch.generation == run.dispatch_generation`).
- Related, deliberately not in this plan: an arq retry of a chat run's cut-off step (plan 003) and queued follow-ups bypassing this outbox in worker mode (plan 004).
