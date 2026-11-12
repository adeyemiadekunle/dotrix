# Plan 035: A long fx conversation turn no longer stops at the journal's size limit

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- apps/backend/src/dotrix_backend/modules/agents/runtime_journal.py`
> If any of these changed, compare the "Current state" excerpts against the
> live code; on a mismatch in the lines this plan changes, treat it as a STOP
> condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `7fb2b01`, 2026-11-12

## Why this matters

An fx chat turn writes every step to an encrypted journal so it can be resumed
after a restart, and periodically saves a checkpoint that replaces everything
before it. But the records a checkpoint replaces are never deleted, and the
size limit (8 MB per run) counts all of them. A long turn with many tool calls
therefore hits "The runtime journal has reached its size limit" and fails, even
though only the records after the last checkpoint are ever read again.

## Current state

`apps/backend/src/dotrix_backend/modules/agents/runtime_journal.py`:

- `MAX_RECORD_BYTES = 2 * 1024 * 1024`, `MAX_JOURNAL_BYTES = 8 * 1024 * 1024`.
- `append` computes, for the run's binding:

```python
            head, total = (await session.execute(select(
                func.coalesce(func.max(AgentRuntimeJournal.sequence), 0),
                func.coalesce(func.sum(AgentRuntimeJournal.byte_count), 0),
            ).where(...binding...))).one()
            if cursor != head or head >= 2**63 - 1:
                raise JournalFenced("The runtime journal has advanced")
            ...
            if total + checkpoint_bytes + len(data) > MAX_JOURNAL_BYTES:
                raise Unprocessable("The runtime journal has reached its size limit")
```

- `save_checkpoint(through, data)` updates or inserts the `AgentRuntimeCheckpoint` row (`through`, `encrypted`, `byte_count`) and deletes nothing. It computes the same `head, total`.
- The loader (just above `append`) reads the checkpoint, then the records with `sequence > start` in order, raising "The runtime journal has a missing record" on a gap; `start` is the checkpoint's `through` when there is one.
- `append` also looks an `idempotency_key` up among existing records to answer a retried append with the saved sequence.

**The trap:** `head` is `max(sequence)` of the remaining rows. If a checkpoint's records are deleted and none remain, `head` becomes 0 and the next append is refused as fenced. `head` must become `max(max(sequence), checkpoint.through)` everywhere it is computed.

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

- `apps/backend/src/dotrix_backend/modules/agents/runtime_journal.py`
- the journal's tests (`grep -rln runtime_journal apps/backend/tests`)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- `fx_pilot.py`, the fx host and libfx: they must see no difference.
- The journal's models and migrations (no schema change is needed).
- `MAX_JOURNAL_BYTES` itself.

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: One place computes the head

Add a private helper that returns `(head, total_bytes, checkpoint)` for a binding, where `head = max(max journal sequence or 0, checkpoint.through or 0)`. Use it in `append`, `save_checkpoint` and the loader, replacing the three inline computations. **Verify**: the existing journal tests pass with no other change.

### Step 2: Delete what a checkpoint replaces

In `save_checkpoint`, after the checkpoint row is written and in the same transaction, `delete(AgentRuntimeJournal)` for the binding where `sequence <= through`. The identical-checkpoint retry path (returns early) deletes nothing.

### Step 3: Retried appends still answer

A retried `append` whose record was pruned can no longer be found by its idempotency key. Decide from the code which it is:
- If a retry for a sequence at or below the checkpoint can only come from an attempt that has since been fenced, answer `JournalFenced` (the cursor check already does: its `expected` is behind `head`). Confirm with a test.
- If the host can legitimately retry such an append and expects the saved sequence, STOP and report.

### Step 4: Changelog

Under Unreleased → Fixed: `- A long reply on the fx runtime no longer fails with "the runtime journal has reached its size limit": steps a checkpoint has replaced are cleared.`

## Test plan

In the journal's test file, against real Postgres as the existing tests do:

1. Append records, save a checkpoint through the last one, then append again: it succeeds and gets `through + 1`.
2. After a checkpoint, the pruned rows are gone (`count` of journal rows with `sequence <= through` is 0) and the loader returns the checkpoint and only the later records.
3. Appending well past 8 MB in total succeeds as long as checkpoints keep the live size under the limit; without a checkpoint the limit still applies.
4. A checkpoint with a cursor beyond the head is still refused; an identical repeated checkpoint is still accepted.
5. A retried append of a pruned record is fenced (Step 3).
6. The existing killed-host recovery test (fx, in `tests/integration`) still passes.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] Tests 1-3 failed before the change and pass now
- [ ] `uv run pytest apps/backend/tests -q -k "journal or fx"` passes
- [ ] ruff clean; release check exit 0
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- The loader or libfx reads records at or below the checkpoint (name the call).
- Step 3's second case.
- `head` is computed somewhere outside this file.

## Maintenance notes

- The limit now bounds the live journal (checkpoint plus the records after it), which is what resuming needs.
- An fx turn that never checkpoints can still reach the limit; if that shows up, the fix is in when the host checkpoints, not here.
