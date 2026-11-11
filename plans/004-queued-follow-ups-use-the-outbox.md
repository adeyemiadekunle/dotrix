# Plan 004: Follow-ups delivered inside the worker are dispatched through the durable outbox

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- apps/backend/src/dotrix_backend/modules/agents/runner.py apps/backend/src/dotrix_backend/worker.py apps/backend/src/dotrix_backend/modules/agents/chat_inputs.py`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED (touches how the worker's runner dispatches; guarded by the full agent test suites)
- **Depends on**: none (do after 003 if both are being done, to keep diffs to `runner.py` separate)
- **Category**: bug
- **Planned at**: commit `f477722`, 2026-11-11

## Why this matters

In worker mode (`DOTRIX_JOBS=worker`), agent runs are supposed to be started
through a durable outbox: a `run_dispatches` row is committed together with the
run, published to the queue after commit, and re-published by a sweep if the
worker dies. That is what makes a run recoverable.

A person can queue a follow-up message while Nova is still answering. When the
current turn finishes, the runner delivers the queued follow-up by creating the
next run. That delivery happens **inside the worker process**, using the
worker's own `AgentRunner`, which is constructed without a `queue`. With no
queue, `prepare_dispatch` records no dispatch row and `_dispatch` executes the
new run inline, nested inside the finishing job. Consequences:

- A crash during the follow-up finds no dispatch row, so the lease sweep marks it failed ("interrupted") instead of recovering it.
- Stop cannot abort it through the queue (there is no job for it).
- A chain of queued follow-ups runs recursively inside one job, under one job timeout.

Two other places in the same package already work around the missing queue
with `runner.queue or runner.stop_reasons`. This plan applies the same rule in
the runner itself, so worker-delivered follow-ups get a dispatch row and a job
of their own.

## Current state

- `apps/backend/src/dotrix_backend/worker.py:80-94` — builds the worker's executing runner:

```python
    ctx["runner"] = AgentRunner(
        session_factory=sessionmaker,
        checkpointer=checkpointer,
        ...
        inline=True,  # this process executes the runs
        stop_reasons=RunQueue(redis),
        streams=RedisRunStreams(redis),
    )
```

  (no `queue=`). `stop_reasons` is a `RunQueue` on the same Redis and queue name
  the API enqueues to.

- `apps/backend/src/dotrix_backend/modules/agents/runner.py:412-420`:

```python
    def prepare_dispatch(
        self, session: AsyncSession, run: AgentRun, payload: dict[str, Any],
    ) -> RunDispatch | None:
        """Record worker dispatch in the caller's transaction; local/inline stay immediate."""
        if self.queue is None:
            if run.dispatch_generation:
                raise Conflict("Continue this run with worker execution enabled")
            return None
        return record_dispatch(session, run, payload, queue_name=self.queue.queue_name)
```

- `runner.py:456-470`:

```python
    async def _dispatch(
        self, run_id: uuid.UUID, payload: dict[str, Any], dispatch: RunDispatch | None = None,
    ) -> None:
        if self.queue is not None:
            if dispatch is None or dispatch.agent_run_id != run_id:
                raise ValueError("Worker runs require dispatch intent committed with their state")
            await RunDispatcher(self.session_factory, self.queue).kick(dispatch.workspace_id, dispatch.id)
            return
        if self.inline:
            await self.execute(run_id, payload)
            return
        task = asyncio.create_task(self.execute(run_id, payload))
        ...
```

- `runner.py:472-477` — `stop()` uses `self.queue` (leave it alone).
- `runner.py:948-951` — after every top-level step, in `execute`'s `finally`:

```python
            if admitted and not original.parent_run_id:
                from .chat_inputs import deliver_queued
                await deliver_queued(self.session_factory, self, workspace_id=original.workspace_id,
                                     thread_id=original.thread_id)
```

- `apps/backend/src/dotrix_backend/modules/agents/chat_inputs.py:272-273` — `deliver_queued` creates the next run with that same runner: `await AgentService(session, runner).create_run(...)`, which calls `runner.prepare_dispatch(...)` then `runner.start(...)` (`agents/service.py:327-335`).

- The existing workaround to copy, `apps/backend/src/dotrix_backend/modules/agents/delegation.py:202`:

```python
        queue = self.runner.queue or self.runner.stop_reasons
```

  and `agents/coding_outcomes.py:117`: `queue = runner.queue or runner.stop_reasons`.

Where `stop_reasons` is set, and to what:

| Runner | `queue` | `stop_reasons` | `inline` |
|---|---|---|---|
| API in worker mode (`main.py`) | `RunQueue` | not set (None) | False |
| API in local / inline mode (`main.py`) | None | not set (None) | False / True |
| Worker's executing runner (`worker.py:80`) | None | `RunQueue` | True |
| Test worker executor (`tests/integration/test_agent_worker.py:42-49`) | None | `RunQueue` | True |

So "`queue or stop_reasons`" is non-None exactly when a real queue exists, and
local/inline mode (both None) is unchanged.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Local services | `pnpm db:up` | Postgres and Redis running |
| Focused tests | `uv run pytest apps/backend/tests/integration/test_agent_worker.py apps/backend/tests/integration/test_chat_inputs.py -q` | all pass |
| All agent-related suites | `uv run pytest apps/backend/tests/integration -q -k "agent or chat or nova or fx or specialist or runtime or coding_outcome or delegation"` | all pass |
| Whole backend (final gate) | `uv run pytest apps/backend -q` | all pass (about 10 minutes) |
| Lint | `uv run ruff check apps packages` | exit 0 |

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/agents/runner.py` (only `prepare_dispatch`, `_dispatch`, and one small helper)
- `apps/backend/tests/integration/test_agent_worker.py` (add one test)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- `worker.py` — do not add `queue=` to the worker's runner; other code distinguishes the API's runner from the worker's by `queue is None`, and `stop()` must keep its current behaviour.
- `AgentRunner.stop`, `chat_inputs.py`, `delegation.py`, `coding_outcomes.py`, `execution/service.py`.
- The recursion depth / job timeout of follow-up chains — solved as a side effect once each follow-up is its own job.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/004-follow-ups-outbox origin/stage`. PRs go into `stage`, never `main`.
- Commit message: one short sentence-case line (e.g. `Follow-ups delivered in the worker go through the dispatch outbox`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write the failing test

Add to `apps/backend/tests/integration/test_agent_worker.py` (it needs the
file's `worker_mode` fixture, which builds an API runner with a queue and a
worker executor with `stop_reasons` only — exactly the production shape):

`test_a_follow_up_delivered_in_the_worker_gets_its_own_dispatch`:

1. `ada, _, base, make_worker = await worker_mode()`; script two replies:
   `agent_script.say("First answer.", "Second answer.")`.
2. Start a run: `POST {base}/agent/runs` with `{"message": "Hi"}` → it is
   `queued` (worker mode). Keep its `id` and `thread_id`.
3. Queue a follow-up for the same conversation while the first run is still
   queued. The route is `POST {base}/agent/threads/{thread_id}/inputs`; read
   `apps/backend/tests/integration/test_chat_inputs.py::test_chat_input_api_is_private_idempotent_and_cancellable`
   (line 49) for the exact body the route expects and copy it.
4. Run the worker once in burst mode: `await make_worker().main()`. The first
   run executes; on finishing, the worker delivers the follow-up.
5. Assert, reading the database through
   `factory = db_client._transport.app.state.runner.session_factory`:
   - a second `AgentRun` exists in that thread (the follow-up), and
   - a `RunDispatch` row exists with `agent_run_id == <follow-up id>`
     (`from dotrix_backend.modules.execution.models import RunDispatch`).
6. Run `await RunDispatcher(factory, queue).sweep()` (where
   `queue = db_client._transport.app.state.runner.queue`) and then
   `await make_worker().main()` again so anything still queued executes; then
   `GET {base}/agent/runs/{follow_up_id}` → `status == "completed"` and
   `reply == "Second answer."`.

**Verify**: `uv run pytest apps/backend/tests/integration/test_agent_worker.py -q -k follow_up` → FAILS before the code change at the "RunDispatch row exists" assertion. If it passes before any code change, STOP.

### Step 2: Use the worker's queue as the outbox

In `AgentRunner` (`modules/agents/runner.py`), add a small property next to
`prepare_dispatch`:

```python
    @property
    def _outbox(self) -> RunQueue | None:
        """The queue runs are dispatched through: the API's in worker mode, and in the worker
        itself the one it reads stop reasons from. None: runs start in this process."""
        return self.queue or self.stop_reasons
```

Use whatever type the constructor already annotates `queue` with (check the
`__init__` signature around line 225-268; if `stop_reasons` is annotated with a
different or wider type, annotate the property's return as `Any` rather than
changing the constructor).

Change `prepare_dispatch` to:

```python
        outbox = self._outbox
        if outbox is None:
            if run.dispatch_generation:
                raise Conflict("Continue this run with worker execution enabled")
            return None
        return record_dispatch(session, run, payload, queue_name=outbox.queue_name)
```

Change the first branch of `_dispatch` to:

```python
        outbox = self._outbox
        if outbox is not None:
            if dispatch is None or dispatch.agent_run_id != run_id:
                raise ValueError("Worker runs require dispatch intent committed with their state")
            await RunDispatcher(self.session_factory, outbox).kick(dispatch.workspace_id, dispatch.id)
            return
```

Leave the `if self.inline:` and task branches, and `stop()`, exactly as they are.

**Verify**: `uv run pytest apps/backend/tests/integration/test_agent_worker.py apps/backend/tests/integration/test_chat_inputs.py -q` → all pass, including the new test.

### Step 3: Find callers that passed no dispatch

After Step 2, a worker-side call to `runner.start(...)` / `runner.continue_run(...)`
/ `runner.resume(...)` **without** a `dispatch=` argument raises
`ValueError("Worker runs require dispatch intent committed with their state")`
where it used to execute inline. Find them:

`grep -n "runner\.\(start\|continue_run\|resume\)(\|self\.\(start\|continue_run\|resume\)(" -r apps/backend/src/dotrix_backend`

For each call site, check that it passes `dispatch=` from a `prepare_dispatch`
call made in the same transaction. Call sites that already do so need no
change. If a call site runs in the worker and passes no dispatch, **STOP and
report it** (file and line) rather than editing it — it is outside this plan's
scope and needs a decision.

**Verify**: `uv run pytest apps/backend/tests/integration -q -k "agent or chat or nova or fx or specialist or runtime or coding_outcome or delegation"` → all pass.

### Step 4: Full backend suite and lint

**Verify**:
- `uv run pytest apps/backend -q` → all pass
- `uv run ruff check apps packages` → exit 0

### Step 5: Changelog

Under `## [Unreleased]` → `### Fixed` in `CHANGELOG.md` add:
`- A follow-up you queued while an agent was answering now survives a worker restart and stops when you press Stop, like any other message.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- One new integration test (Step 1) in `test_agent_worker.py`, using the existing `worker_mode` fixture.
- Regression guards: all of `test_chat_inputs.py` (queue ordering, atomic dispatch, recovery without duplicates) and `test_agent_worker.py` must pass unchanged.

## Done criteria

- [ ] New test present, passing, not skipped
- [ ] `uv run pytest apps/backend -q` exits 0
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `grep -n "_outbox" apps/backend/src/dotrix_backend/modules/agents/runner.py` shows the property and its two uses
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- The excerpts in "Current state" do not match the live code.
- Redis is unreachable so the worker tests are skipped — do not mark done on skipped tests.
- Step 3 finds a worker-side call that passes no dispatch.
- Any existing test fails after Step 2 and the cause is not an obvious typo in your edit. In particular, tests that build an executor with `stop_reasons` and expect child or follow-up runs to execute inline in the same call: report the test name and the failure; do not change the test to fit.
- The fix seems to require editing `worker.py`, `stop()`, or `execution/service.py`.

## Maintenance notes

- After this change, "has a queue" is expressed as `runner._outbox is not None`. The two existing `runner.queue or runner.stop_reasons` expressions (`delegation.py:202`, `coding_outcomes.py:117`) could later be replaced with `runner._outbox` (made public); deliberately not done here to keep the diff small.
- A reviewer should run the worker-mode tests with Redis available and confirm they were not skipped.
- If the worker's runner is ever given `queue=` directly, the `_outbox` property becomes redundant; remove it then, do not keep both.
