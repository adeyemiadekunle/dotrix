# Plan 036: A GitHub delivery's follow-up jobs are still scheduled when queueing them fails the first time

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- apps/backend/src/dotrix_backend/modules/connectors/router.py apps/backend/src/dotrix_backend/modules/connectors/webhook.py apps/backend/src/dotrix_backend/modules/connectors/models.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MEDIUM
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

A GitHub webhook delivery is applied in two parts: the database changes are
committed, then follow-up jobs are queued (syncing the checkout after a push,
Juno's look at a failed CI run). If queueing fails (Redis is briefly away), the
handler forgets the delivery so GitHub's retry applies it again. But applying
it again re-runs changes that were already committed, and handlers that act
"once" (Juno's CI look is started once per commit) see their work as done and
return no follow-up the second time. The job is then never queued: the checkout
stays stale, or the failed CI is never looked at.

## Current state

`apps/backend/src/dotrix_backend/modules/connectors/router.py`, `github_webhook` (lines ~176-188):

```python
    if x_github_delivery and not await webhook.first_delivery(session, x_github_delivery, x_github_event):
        logger.info("github webhook %s: delivery %s already applied", x_github_event, x_github_delivery)
        return {"result": "duplicate"}
    done, follow_ups = await webhook.handle(session, x_github_event, payload, settings)
    await session.commit()  # the delivery's record, when handling changed nothing
    logger.info("github webhook %s: %s", x_github_event, done)
    try:
        for name, kwargs in follow_ups:  # checkouts behind a push; Juno's look at a failed CI
            await jobs.enqueue(name, **kwargs)
    except Exception:
        if x_github_delivery:  # so GitHub's retry is applied again and schedules the jobs
            await webhook.forget_delivery(session, x_github_delivery)
        raise
    return {"result": done}
```

`apps/backend/src/dotrix_backend/modules/connectors/models.py`: `GitHubDelivery(delivery_id, event, received_at)`, kept a week.
`follow_ups` is a list of `(job name, kwargs)` with JSON-friendly kwargs (ids as strings); confirm in `webhook.handle` and `ci_completed`.
The repo has a durable dispatch pattern for runs (`modules/execution`, `run_dispatches`: intent committed with the change, published after commit, republished by a sweep); this plan uses the same idea at a smaller size.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `uv run pytest apps/backend/tests -q -k "<the tests you add>"` | pass |
| Lint | `uv run ruff check apps packages` | All checks passed |
| Release check | `python scripts/release.py check` | exit 0 |
| Format | `pnpm format:check` | exit 0 |

Integration tests need Postgres and Redis (`pnpm db:up`) and the `DOTRIX_*` test variables described in `CLAUDE.md`.

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/connectors/router.py`, `webhook.py`, `models.py`
- one Alembic migration (a nullable JSON column on `github_deliveries`)
- `apps/backend/src/dotrix_backend/jobs.py` or `worker.py` only if Step 3's sweep hooks into an existing periodic job
- the webhook tests (`grep -rln github_webhook apps/backend/tests`)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- What each event handler does (`webhook.handle`'s branches).
- `modules/execution`.

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: Confirm the loss with a test

Write the failing test first: a `check_suite` failure delivery with `jobs.enqueue` raising once. Then redeliver the same delivery id with a working queue. Assert the Juno CI job is queued exactly once overall. Do the same for a `push` (the sync job). If both already pass on today's code, STOP and report: the finding is wrong for those handlers.

### Step 2: Record the follow-ups with the delivery

Add `pending: Mapped[list | None]` (JSON, nullable) to `GitHubDelivery`. After `handle` returns, store `follow_ups` in it on the delivery's row, in the same commit as the changes. After every job is queued, set it to `None` and commit. Remove the `forget_delivery` call from this path: a failed enqueue now returns 503 with the delivery kept and `pending` set.

### Step 3: A redelivery, or the sweep, finishes the job

- In the handler's duplicate branch: if the delivery's row has `pending`, queue those jobs, clear it, and answer `{"result": "resumed"}`; otherwise `duplicate` as today.
- So a delivery isn't stuck when GitHub doesn't retry: add the same "queue what's pending, then clear" to the periodic cleanup that already deletes stale deliveries (`delete_stale_deliveries`'s caller), for rows older than a minute. Take rows `FOR UPDATE SKIP LOCKED` so two sweeps don't queue twice.

Queueing then clearing can queue a job twice if the process dies in between; check that the two jobs (`sync_repository`, Juno's CI look) tolerate a repeat, and say so in the report.

### Step 4: Migration and changelog

`pnpm db:revision "webhook follow-ups"`; `alembic check` clean. Under Unreleased → Fixed: `- A push or a failed CI run reported by GitHub while the job queue is briefly unavailable is still followed up (the checkout synced, Juno asked to look); before, it could be skipped.`

## Test plan

1. Step 1's two tests (CI failure, push).
2. Enqueue fails, no redelivery, the sweep runs: the job is queued once and `pending` is cleared.
3. A plain duplicate delivery (nothing pending) still answers `duplicate` and queues nothing.
4. Delivery ids are still required and validated as before (existing tests stay green).

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] Step 1's tests failed before and pass now
- [ ] `uv run alembic -c apps/backend/alembic.ini check` clean
- [ ] `grep -n forget_delivery apps/backend/src -r` shows it is no longer called from the enqueue failure path (delete the function if nothing else uses it)
- [ ] ruff clean; release check exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- Step 1's tests pass on the current code.
- A follow-up's kwargs aren't JSON-serializable.
- A job is not safe to run twice.

## Maintenance notes

- New webhook handlers need nothing special: whatever they return as follow-ups is stored and retried.
