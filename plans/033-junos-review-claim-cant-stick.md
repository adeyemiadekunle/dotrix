# Plan 033: Juno's review is still posted on the pull request after a failed or interrupted attempt

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 7fb2b01..HEAD -- apps/backend/src/dotrix_backend/modules/coding/github_reviews.py`
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

Before Juno's review (or its look at a failed CI run) is posted on a pull
request, the turn is claimed by writing the word `posting` where the review's
link will go. The claim is released only if posting fails with one of two
expected errors. Any other failure (a network error from the HTTP client, a
malformed finding, the worker being stopped mid-post) leaves `posting` there for
good. Every later attempt then sees "posted already, or being posted" and
returns, so that turn's review never reaches GitHub, and Codes shows no review
link.

## Current state

`apps/backend/src/dotrix_backend/modules/coding/github_reviews.py`:

```python
POSTING = "posting"  # the claim on a turn's review (or CI look) while it's being posted
```

`post_review` (lines ~152-218): under a row lock it returns early when
`run.ci_review_posted_url if is_ci else run.review_posted_url` is truthy, else
sets it to `POSTING` and commits. Then:

```python
    try:
        token = await app.access_token(...)
        ...
            url = await app.post_review(...)
    except (Forbidden, GitHubUnavailable) as exc:
        logger.warning(...)
    async with ctx.session_factory() as session:
        held = await session.get(CodingRun, coding_id, with_for_update=True, populate_existing=True)
        if held is not None:
            posted = (url or held.pr_url) if url is not None else None  # None again: the next finish may retry
```

Only `Forbidden` and `GitHubUnavailable` reach the block that resets the claim.
`review_posted_url` and `ci_review_posted_url` are string columns on `CodingRun`.
Find everything that reads them with `grep -rn "review_posted_url" apps/backend/src apps/web apps/cli` (the API's schema shows the link in Codes).

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

- `apps/backend/src/dotrix_backend/modules/coding/github_reviews.py`
- `apps/backend/src/dotrix_backend/modules/coding/schemas.py` or wherever the URL is serialized, only to keep a claim from being shown as a link
- the tests for `post_review` (find with `grep -rln post_review apps/backend/tests`)
- `CHANGELOG.md` (one line under Unreleased, in the existing section of its kind; never add a second heading)

**Out of scope** (do NOT touch):

- Juno's review run itself and how it is started.
- The GitHub App client (`connectors/github_app.py`).

## Git workflow

- Work on the branch the reviewer gives you. Otherwise branch from `stage` and open the PR into `stage`, never `main`.
- Commit messages: one short sentence-case line.
- Do NOT push or open a PR unless instructed. Never use bare `git stash`.

## Steps

### Step 1: Always release the claim

Wrap the posting block so the claim is released whatever happens: move the second session block (the one that writes `posted`) into a `finally`, with `url` still `None` on any exception. Keep the warning log for the two expected errors; log unexpected ones with `logger.exception` and re-raise after the `finally` has run, so the job is reported as failed.

### Step 2: A claim left by a dead worker expires

A worker killed mid-post never runs `finally`. Make the claim carry its time: write `f"{POSTING}:{int(time.time())}"` instead of the bare word, and treat a claim as free when it is the bare word (left by the old code) or older than `CLAIM_SECONDS = 600`. Add a small `_claimed(value: str | None) -> bool`: false for `None`, for a stale or bare claim; true for a fresh claim; true for anything else (a real URL).

### Step 3: A claim is never shown as a link

Check what the API returns for these two fields while a claim is held (`grep` from "Current state"). If the raw value is serialized, return `None` when it starts with `posting`. If the code already hides it, say where in your report and change nothing.

### Step 4: Changelog

Under Unreleased → Fixed: `- Juno's review of a pull request is posted on a later attempt when an earlier one failed or was interrupted; before, it could be skipped for good.`

## Test plan

Beside the existing `post_review` tests, with the fake GitHub App they use:

1. `post_review` where the fake's `post_review` raises `RuntimeError`: the job raises, and `review_posted_url` is `None` afterwards; a second call with a working fake posts and records the URL.
2. A run whose `review_posted_url` is the bare `"posting"` (the old stuck state): `post_review` posts.
3. A fresh claim (`posting:<now>`): `post_review` returns without posting.
4. A stale claim (`posting:<now - 601>`): posts.
5. The same four through the CI path (`ci_review_posted_url`) can be one parametrized test.
6. The API never returns a value starting with `posting` for either field.

Every new test must fail on the code before your change. Check that (a temporary WIP commit, then the old source checked out) and say how in your report.

## Done criteria

- [ ] Tests 1, 2 and 4 failed before the change and pass now
- [ ] `grep -n '= POSTING$' apps/backend/src/dotrix_backend/modules/coding/github_reviews.py` finds no bare-word claim being written
- [ ] ruff clean; `python scripts/release.py check` exit 0; `pnpm openapi` leaves no diff (run it if a schema changed)
- [ ] `git status --short` shows only in-scope files
- [ ] `plans/README.md` status row updated (unless the reviewer maintains it)

## STOP conditions

- The fields are compared to `POSTING` somewhere outside this file in a way a timestamped claim breaks.
- A double post becomes possible (two workers both treating one claim as free): the check and the claim must stay under the same row lock.

## Maintenance notes

- A post that reached GitHub but whose response was lost can be posted twice after the claim expires. That is the lesser harm; GitHub shows both, and the audit log records each.
