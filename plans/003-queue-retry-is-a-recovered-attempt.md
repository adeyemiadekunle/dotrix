# Plan 003: A chat step retried by the queue runs as a recovered attempt (Manual, no repeated tool calls)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- apps/backend/src/dotrix_backend/modules/agents/runner.py apps/backend/src/dotrix_backend/worker.py apps/backend/src/dotrix_backend/modules/execution/service.py`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (retried steps ask for approval more often)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `f477722`, 2026-11-11

## Why this matters

The product rule (written in the repo's `CLAUDE.md`) is: "A recovered attempt
runs in Manual (no standing rules or Accept edits), and tool calls the cut-off
attempt left unanswered get a 'Cut off' result instead of running again, so no
change goes through twice unasked."

That rule is applied only when the run's payload carries `"recovered": True`,
which only the lease sweep (`expire_agent_leases`) sets. There is a second way
a step gets cut off and retried: the worker process is stopped (every deploy or
graceful shutdown), the step's job is cancelled, and **arq retries the same
job**. That retry arrives with `retry_operation=True` and the run still
`RUNNING`, but the payload has no `recovered` flag. So the retried step keeps
Accept edits / Auto and re-runs the pending tool calls, and a write tool
(create an issue, write a document) whose effect already landed can run a
second time with no approval. After this plan, a queue retry of a run that is
still RUNNING is treated exactly like a recovered attempt.

This affects the DeepAgents chat runtime. The fx runtime already claims each
change in `agent_runtime_calls` before running it.

## Current state

- `apps/backend/src/dotrix_backend/worker.py:112-125` — the `run_agent` job passes `retry_operation=ctx.get("job_try", 1) > 1`.
- `apps/backend/src/dotrix_backend/modules/execution/service.py:134-135` — `accept_operation` re-admits an already-accepted dispatch only for `retry and isinstance(run, AgentRun) and run.status is RunStatus.RUNNING`.
- `apps/backend/src/dotrix_backend/modules/agents/runner.py` — `AgentRunner.execute` (line 493) for project conversations, `_execute_across` (line 953) for conversations across projects, `_unattended_specs` (line 339), and the module-level `_continue_from_checkpoint` (line 1578).

`worker.py:122-125`:

```python
    if operation is not None:
        await runner.execute(
            operation.run_id, operation.payload, operation=operation,
            retry_operation=ctx.get("job_try", 1) > 1,
        )
```

`runner.py:527-542` (inside `execute`; the run row is locked here):

```python
            async with self.session_factory() as session:
                query = select(AgentRun).where(AgentRun.id == run_id)
                if operation is not None:
                    query = query.where(AgentRun.workspace_id == operation.workspace_id)
                run = await session.scalar(query.with_for_update())
                if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
                    logger.info("agent run %s: nothing to do (%s)", run_id, run and run.status)
                    return
                if not await accept_operation(session, run, operation, retry=retry_operation):
                    return
                admitted = True
                # A previous attempt was cut off, or the person continues one that stopped at a limit.
                retry = run.status is RunStatus.RUNNING or payload["kind"] == "continue" or bool(payload.get("recovered"))
```

`runner.py:607-609` (the approval mode for this attempt reads only the payload):

```python
                specs, unattended_left, accepted, approval = await self._unattended_specs(
                    session, run, specs, resolved, recovered=bool(payload.get("recovered")),
                )
```

`runner.py:1587-1596` (the "Cut off" tool results are added only when the payload says recovered):

```python
        if payload.get("recovered") and "tools" in state.next:
            # Its worker stopped while tools ran: one may have taken effect already. Rather than
            # running them again unasked, each unanswered call says so; the agent checks, and any
            # change it repeats asks for approval (a recovered attempt runs in Manual).
            cut = _unanswered_calls(state.values)
            if cut and not any(call.get("name") == "delegate_tasks" for call in cut):
                await agent.aupdate_state(config, {"messages": [
                    ToolMessage(content=CUT_OFF_TOOL, tool_call_id=call["id"], name=call.get("name"))
                    for call in cut if call.get("name") != "delegate_tasks"
                ]}, as_node="tools")
```

`payload` is a plain `dict` passed down to `_continue_from_checkpoint`
(`runner.py:864` and `:1040`) and recorded at `runner.py:322`
(`"recovered": bool(payload.get("recovered"))`). So the smallest correct
change is to add `"recovered": True` to the payload, once, at the point where
the row is locked and the attempt has been admitted.

`_execute_across` has the same shape at `runner.py:962-972`:

```python
                run = await session.scalar(query.with_for_update())
                if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
                    return
                if not await accept_operation(session, run, operation, retry=retry_operation):
                    return
                retry = run.status is RunStatus.RUNNING or payload["kind"] == "continue" or bool(payload.get("recovered"))
```

An existing test must keep passing unchanged and shows the boundary of this
fix: `apps/backend/tests/integration/test_agent_worker.py::test_a_retried_step_does_not_resend_the_message`
calls `runner.execute(run_id, {"kind": "start", ...})` with **no** `operation`
and **no** `retry_operation` on a RUNNING run, and expects the finished step's
outcome to be recorded from the checkpoint. Because this plan keys only on
`retry_operation`, that path is untouched.

The existing test for the recovered behaviour, to model the new test on:
`apps/backend/tests/integration/test_agent_leases.py::test_a_run_cut_off_mid_write_resumes_without_writing_twice_unasked`
(lines 96-130). It makes a `write_file` land and then raises, and asserts the
resumed attempt receives a tool message starting with `"Cut off:"` and ends in
`awaiting_approval`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Local services | `pnpm db:up` | Postgres and Redis running |
| Focused tests | `uv run pytest apps/backend/tests/integration/test_agent_leases.py apps/backend/tests/integration/test_agent_worker.py -q` | all pass |
| Wider agent suites | `uv run pytest apps/backend/tests/integration/test_agents.py apps/backend/tests/integration/test_chat_inputs.py apps/backend/tests/integration/test_nova_team.py -q` | all pass |
| Lint | `uv run ruff check apps packages` | exit 0 |

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/agents/runner.py` (only the two admission blocks described below)
- `apps/backend/tests/integration/test_agent_leases.py` (add one test)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- `worker.py` and `execution/service.py` — `retry_operation` is already passed correctly.
- `_continue_from_checkpoint` and `_unattended_specs` themselves — they already behave correctly when the payload says recovered.
- The fx runtime (`agents/fx_pilot.py`, `fx_tools.py`).
- Token-usage loss on retried attempts (a known, documented gap in a comment at `runner.py:517-519`).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/003-queue-retry-recovered origin/stage`. PRs go into `stage`, never `main`.
- Commit message: one short sentence-case line (e.g. `A queue retry of a cut-off chat step runs as a recovered attempt`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write the failing test

Add to `apps/backend/tests/integration/test_agent_leases.py` a test modelled
on `test_a_run_cut_off_mid_write_resumes_without_writing_twice_unasked`
(reuse that file's helpers `_team`, `_factory`, `WorkerDied` and its imports):

`test_a_queue_retry_of_a_cut_off_step_asks_before_repeating_a_change`:

1. Make `PlatformKnowledgeBackend.awrite` land the write and then raise
   `WorkerDied` (same monkeypatch as the model test).
2. Script the model: `agent_script.say(tool_call("write_file", file_path="/dotrix/roadmap.md", content="# The plan"), "Written.")`
   and start a run with `"approval_mode": "accept_edits"`; expect `WorkerDied`.
3. Restore `awrite`. The run row is now `RUNNING` (the attempt died mid-step).
   Look its id up as the model test does.
4. Simulate arq retrying the same job: script the model again with the same
   `tool_call(...)` then `"Waiting for approval."`, then call the app's runner
   directly with `retry_operation=True`:
   `runner = db_client._transport.app.state.runner` and
   `await runner.execute(run_id, {"kind": "start", "message": "Write the plan down"}, retry_operation=True)`.
   If the run's lease from the dead attempt blocks the new attempt (the test
   hangs or the run is skipped), first lapse it with the file's existing
   `_lapse(db_client, str(run_id))` helper — do **not** call
   `expire_agent_leases` in this test, because that is the other recovery path.
5. Assert: among the tool messages the model received on the retry, the last
   one starts with `"Cut off:"`; the run's status is `awaiting_approval`; and
   its approvals are `["write_file"]` (same assertions as the model test,
   lines 124-130).

**Verify**: `uv run pytest apps/backend/tests/integration/test_agent_leases.py -q -k queue_retry` → FAILS before the code change (the run completes or the write runs again without approval). If it passes before any code change, STOP.

### Step 2: Mark the attempt recovered in `execute`

In `AgentRunner.execute`, immediately after `admitted = True` (line ~539) and
before the `retry = ...` line, add:

```python
                if retry_operation and run.status is RunStatus.RUNNING:
                    # The queue is retrying a step its worker was cut off in (a deploy, a shutdown):
                    # the same as a lapsed lease. It runs in Manual, and unanswered tool calls
                    # aren't run again unasked.
                    payload = {**payload, "recovered": True}
```

`payload` is a parameter of `execute`; rebinding it here makes every later use
in this method (the `retry` line, `_unattended_specs(..., recovered=...)`,
`_continue_from_checkpoint(..., payload, ...)`, and the recorded step event)
see the flag. Do not mutate the dict in place (`operation.payload` is shared).

### Step 3: Do the same in `_execute_across`

In `_execute_across`, immediately after its `accept_operation` check and before
its `retry = ...` line (line ~972), add the same four lines.

**Verify**: `uv run pytest apps/backend/tests/integration/test_agent_leases.py apps/backend/tests/integration/test_agent_worker.py -q` → all pass, including the new test and the unchanged `test_a_retried_step_does_not_resend_the_message`.

### Step 4: Wider suites and lint

**Verify**:
- `uv run pytest apps/backend/tests/integration/test_agents.py apps/backend/tests/integration/test_chat_inputs.py apps/backend/tests/integration/test_nova_team.py -q` → all pass
- `uv run ruff check apps packages` → exit 0

### Step 5: Changelog

Under `## [Unreleased]` → `### Fixed` in `CHANGELOG.md` add:
`- A reply cut off by a worker restart and retried no longer repeats a change that had already gone through: the retried step asks for approval first, as a recovered run does.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- One new integration test (Step 1) in `test_agent_leases.py`, modelled on the existing mid-write test in the same file.
- Regression guard: `test_agent_worker.py::test_a_retried_step_does_not_resend_the_message` and `::test_a_run_whose_worker_stopped_goes_on_in_another` must pass unchanged.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_agent_leases.py apps/backend/tests/integration/test_agent_worker.py -q` exits 0 with the new test present and not skipped
- [ ] The Step 4 suites pass; `uv run ruff check apps packages` exits 0
- [ ] `grep -c '"recovered": True}' apps/backend/src/dotrix_backend/modules/agents/runner.py` is 2 higher than before this plan
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- The excerpts in "Current state" do not match the live code.
- The new test passes before the code change.
- Making the new test pass seems to require changing `_continue_from_checkpoint`, `_unattended_specs`, or `accept_operation`.
- Any existing test fails after the change — in particular any test that relies on a queue retry continuing in Accept edits / Auto. Report the test name; do not weaken it.

## Maintenance notes

- This makes a queue retry stricter (Manual) than before. That is the documented rule; if the product ever wants a retried step with no pending tool calls to keep its approval mode, the place to refine is the new `if` in `execute`, by inspecting the checkpoint for unanswered calls first.
- A reviewer should check both blocks (`execute` and `_execute_across`) and that `operation.payload` is never mutated.
- Not covered here: `delegate_tasks` calls are deliberately excluded from the "Cut off" handling by existing code; that is unchanged.
