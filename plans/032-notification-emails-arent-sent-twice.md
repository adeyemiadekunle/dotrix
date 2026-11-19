# Plan 032: A crash while emailing notifications doesn't email everyone again

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- apps/backend/src/dotrix_backend/modules/notifications/emails.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

The job that emails notifications sends every email first and records that it
did so only at the very end, in one commit. If the worker stops in between (a
deploy, a crash, a database error on the final commit), none of the up to 1,000
notifications is marked, and the next run emails all of them again. While it
sends, it also holds row locks on all of them.

After this plan each person's notifications are marked and committed before
their email goes out, so a crash can repeat nothing. The cost is that a crash
in the instant between the commit and the send loses that one email; the
notification itself is still in the person's Inbox. That is already how a
failed send behaves today (it is logged and the rows are marked handled).

## Current state

`apps/backend/src/dotrix_backend/modules/notifications/emails.py`, `send_pending` (lines ~94-120):

```python
        rows = list((await self.session.execute(
            select(Notification, User, Workspace.slug, Project.key)
            ...
            .where(Notification.emailed_at.is_(None), Notification.created_at <= now - BATCH_WAIT)
            .order_by(Notification.created_at)
            .limit(1000)
            .with_for_update(of=Notification, skip_locked=True)
        )).all())
        ...
        for user, items in by_user.values():
            wanted = await self._wanted(user, items) if user.email_notifications == "immediately" else []
            if wanted:
                sent += await self._send(user, wanted, digest=False)
        if rows:
            await self.session.execute(
                update(Notification).where(Notification.id.in_([n.id for n, *_ in rows])).values(emailed_at=now)
            )
        await self.session.commit()
```

`_send` (line ~192) catches every exception from `self.sender.send(...)`, logs it and returns 0.
`send_digests` (below it) has its own bookkeeping; read it in Step 1.

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

- `apps/backend/src/dotrix_backend/modules/notifications/emails.py`
- `apps/backend/tests/integration/test_notifications*.py` (the file that already tests `send_pending`)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- The notification model and how notifications are created (`notify.py`).
- Email templates and the sender (`core/email.py`, `core/jobs.py`).

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: Read both senders

Read `send_pending` and `send_digests` in full. Note for the report how `send_digests` records what it sent, and whether it has the same order problem (send first, record after). If it does, apply Step 2's order to it too; if its bookkeeping is a different shape (a per-user timestamp), make the same change there: record and commit, then send.

### Step 2: Mark, commit, then send, one person at a time

In `send_pending`, keep the single locked select. Then for each person:

1. Work out `wanted` as today (this only reads).
2. `update(Notification)...values(emailed_at=now)` for that person's rows, then `await self.session.commit()`.
3. Then `_send(user, wanted, digest=False)`.

A commit releases the row locks taken by the select, so after the first person's commit the rest of the batch is unlocked. That is safe only if a second worker can't pick the same rows up meanwhile: mark **all** selected rows first in one update and commit (releasing the locks with everything marked), then send person by person. Prefer that simpler form:

1. Select and lock (as today).
2. Compute `wanted` per person.
3. One update marking every selected row, commit.
4. Send each person's email.

**Verify**: the existing notification email tests pass unchanged.

### Step 3: Changelog

Under Unreleased → Fixed: `- A restart while notification emails are going out no longer sends the same emails again.`

## Test plan

In the existing notifications email test file, with the fake sender the tests already use:

1. **Crash after sending.** A sender whose second `send` raises `BaseException`-level failure isn't needed; simulate the crash by making the sender raise an exception `_send` doesn't swallow (patch `_send` itself to raise on the second person). Run `send_pending` (it raises), then run it again with a working sender: the first person gets no second email, and no notification is left with `emailed_at` null.
2. **Normal run** still sends one email per person and marks every row (existing tests cover this; keep them green).

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] The new test passes and failed before the change
- [ ] `uv run pytest apps/backend/tests -q -k notification` passes
- [ ] `uv run ruff check apps packages` clean; `python scripts/release.py check` exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- `send_pending` no longer matches the excerpt.
- Marking before sending would change which notifications a digest later includes (say how).

## Maintenance notes

- Delivery is at most once by design: the Inbox is the record, email is a nudge. If guaranteed delivery is ever wanted, it needs an outbox row per email, not a reordering.
