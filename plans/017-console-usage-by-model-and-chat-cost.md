# Plan 017: The console shows what chat costs and how each model is doing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 78f46c1..HEAD -- apps/backend/src/dotrix_backend/modules/admin apps/backend/src/dotrix_backend/core/model_prices.py apps/admin/src`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition. (Earlier plans in this series change
> some of the same files; where "Depends on" names a plan, its changes are
> expected.)

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (read-only additions)
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `78f46c1`, 2026-11-11

## Why this matters

Everyone on dotrix runs on their own model keys, so which providers and models are in use, which are failing, and which are hitting their limits is the most useful thing an operator can know about usage. Today the console shows tokens per day and the cost of coding turns only; chat runs have tokens but no cost, and nothing is broken down by model except a top-ten list of failures. After this plan there is a Models page: runs, failures, limit stops, tokens and an estimated cost per model and per provider, and the Overview's cost includes chat.

## Current state

The console's data comes from `apps/backend/src/dotrix_backend/modules/admin/platform.py` (`PlatformObserve`: `health`, `counts`, `trends`, `failures`, `coding`, `workspaces`, `audit`), exposed read-only by `modules/admin/router.py` under `/v1/admin/observe/*` and `/v1/admin/audit`, with response models in `modules/admin/schemas.py`. Every route takes `admin: AdminDep`. The console's pages are in `apps/admin/src/pages.tsx` (Overview, Runs, Failures, Coding, Workspaces, Audit), its response types in `apps/admin/src/api.ts`, charts in `charts.tsx`, tables in `table.tsx`. Pages poll with TanStack Query (`refetchInterval`, 15 s for health, 60 s for the rest). Tests: `apps/backend/tests/integration/test_admin.py` builds runs directly with `_chat_run` / `_coding_run` from `tests/integration/test_observe.py`.

Chat runs are `AgentRun` rows (`modules/agents/models.py`): `model` and `conversation_model` (`String(100)`, "provider:model"; the code elsewhere uses `func.coalesce(AgentRun.conversation_model, AgentRun.model)`), `input_tokens`, `output_tokens`, `cached_input_tokens`, `status`, `error_kind` (e.g. `"model_limit"`, `"interrupted"`), `finished_at`, `created_at`. Coding turns are `CodingRun` rows with their own `model`, `agent` (the engine), token columns and `cost_usd`.

Prices are in `core/model_prices.py`:

```python
PRICES: dict[str, tuple[float, float, float, float]] = {
    "anthropic:claude-opus-5-5": (4.0, 0.20, 5.0, 20.0),
    ...
}

def cost_of(model: str | None, *, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0,
            cache_write_tokens: int = 0, overrides: dict[str, list[float]] | None = None) -> float | None:
    """The cost in USD of a turn's tokens on `model` ("provider:model"); `input_tokens` includes the
    cached reads and writes. None when the model has no price."""
```

with `settings.model_prices` as `overrides`. Its docstring's rule matters here: "A model without a price gets no cost, never a guess."

`PlatformObserve.trends` builds `DayStats` per UTC day (`chat_runs`, `chat_failed`, `coding_runs`, `coding_failed`, `input_tokens`, `output_tokens`, `coding_cost_usd`, `signups`); `PlatformObserve.coding` is the pattern for a grouped breakdown (`CodingBreakdown` rows by engine and location). The console's Coding page (`CodingPage` in `pages.tsx`) is the pattern for a breakdown table with a window selector (`Segmented` with `DAYS`).

Repo conventions that apply (from the repository's `CLAUDE.md`):

- Backend layering is router → service; routers never query. Raise domain exceptions from `dotrix_backend.core.errors`, never `HTTPException`.
- Pydantic v2 schemas are separate from ORM models; never return ORM objects.
- Every schema change is one Alembic migration in `apps/backend/migrations/versions/` (`YYYYMMDD_HHMM_<12 hex>_<slug>.py`, `revision`, `down_revision` = the current head from `uv run --directory apps/backend alembic heads`, working `upgrade()` and `downgrade()`). CI runs `alembic check`.
- Every route has a docstring and `responses=errors(...)`; route function names are the OpenAPI operation IDs. After any API change run `pnpm openapi` and commit `packages/api-client/openapi.json` and `src/schema.ts`.
- Never log a token, password or secret. Secrets at rest are encrypted with `core/crypto.py` `Secrets` (Fernet, `DOTRIX_ENCRYPTION_KEY`).
- The admin console must never show what people wrote (conversation text, document text, audit `details`, raw provider messages).
- UI copy is sentence case. The admin console calls the API only through `apps/admin/src/api.ts`; its pages are in `apps/admin/src/pages.tsx`, its types in `api.ts`, its styles in `admin.css`.
- Every PR adds a line under `## [Unreleased]` in `CHANGELOG.md`, in the existing section of the right kind.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync && pnpm install` | exit 0 |
| Local services (tests need Postgres and Redis) | `pnpm db:up` | containers running |
| Admin tests | `uv run pytest apps/backend/tests/integration/test_admin.py -q` | all pass |
| OpenAPI docs rules | `uv run pytest apps/backend/tests/unit/test_openapi.py -q` | all pass |
| Migrations match models | `uv run --directory apps/backend alembic upgrade head && uv run --directory apps/backend alembic check` | "No new upgrade operations detected" |
| Python lint | `uv run ruff check apps packages` | exit 0 |
| Regenerate API schema + client | `pnpm openapi` | exit 0 |
| TS checks | `pnpm typecheck && pnpm exec eslint . && pnpm format:check && pnpm --filter @dotrix/admin build` | exit 0 |
| Release check | `python scripts/release.py check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `apps/backend/src/dotrix_backend/modules/admin/platform.py`, `schemas.py`, `router.py`
- `apps/backend/tests/integration/test_admin.py` (add tests)
- `apps/admin/src/App.tsx` (one nav entry), `api.ts`, `pages.tsx`, `charts.tsx` if a chart changes
- `packages/api-client/*` (via `pnpm openapi`), `CHANGELOG.md`

**Out of scope** (do NOT touch):

- Storing a cost on `AgentRun` (a schema change): costs here are computed when read, from tokens and today's prices.
- Adding or changing prices in `core/model_prices.py`.
- Per-person usage, or anything inside a workspace's own Settings.
- Latency per provider (not recorded on runs).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/017-console-usage-by-model-and-chat-cost origin/stage`. PRs go into `stage`, never `main`.
- Commit messages: one short sentence-case line describing the change.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: The breakdown

In `schemas.py`:

```python
class ModelUsage(BaseModel):
    """One model's use in the window, chat and coding together."""

    model: str = Field(description='"provider:model", or "(default)" when a run recorded none')
    provider: str
    chat_runs: int
    coding_runs: int
    failed: int
    limit_stops: int = Field(description="Chat runs the provider stopped for its limits")
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = Field(description="Estimated from tokens and list prices; None when the model has no price")
    cost_is_estimate: bool = True
```

In `platform.py` add `async def models(self, days: int = 7) -> list[ModelUsage]`: one grouped query over `AgentRun` (group by the coalesced model; sum tokens including `cached_input_tokens`; count failed and `error_kind == "model_limit"`), one over `CodingRun` (group by `model`; sum tokens and the recorded `cost_usd`), merged in Python by model. Chat cost is `cost_of(model, input_tokens=…, output_tokens=…, cached_input_tokens=…, overrides=self.settings.model_prices)` on the group's sums; coding cost is the recorded sum. When a model has chat tokens but no price, `cost_usd` is the coding part alone if there is one, else `None` — never a guess. `provider` is the text before the first `:` (or `"unknown"`). Sort by total runs, descending; cap at 50 rows.

Route: `GET /v1/admin/observe/models` with `days: Days = 7`, docstring and `responses=errors(422)` like its neighbours.

### Step 2: Chat cost in the daily trend

`DayStats` gains `chat_cost_usd: float = 0.0` and `unpriced_chat_runs: int = 0`. In `trends`, group chat runs by day **and** model, apply `cost_of` per group, and sum per day; count runs on models with no price in `unpriced_chat_runs` so the console can say the figure is partial.

### Step 3: Tests

In `tests/integration/test_admin.py`, using `_chat_run` / `_coding_run` (they accept keyword overrides such as `model=`, `input_tokens=`, `status=`): two chat runs on a priced model and one on an unpriced one → the priced model's `cost_usd` equals `cost_of` on the summed tokens, the unpriced model's is `None`; a `model_limit` failure counts in `limit_stops` and `failed`; coding cost comes from the recorded `cost_usd`; `trends` reports `chat_cost_usd` for the day and `unpriced_chat_runs == 1`; the response contains no run titles or messages (seed a run with a distinctive `title` and `message` and assert neither appears).

**Verify**: `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_openapi.py -q` → all pass

### Step 4: The console

`pnpm openapi`. Add a "Models" page to `PAGES` built like `CodingPage`: a window selector, a table (model, provider, chat runs, coding turns, failed, limit stops, tokens, cost) and, above it, the same figures summed per provider. Show `—` for a `None` cost, and a note under the table: "Cost is an estimate from tokens and list prices; models without a listed price show none." On the Overview, the 7-day cost becomes coding plus chat, with "partial" beside it when `unpriced_chat_runs > 0`.

### Step 5: Changelog

Unreleased → Added: `- The admin console has a Models page (runs, failures, limit stops, tokens and estimated cost per model and provider), and its cost figures include chat.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- New tests in `tests/integration/test_admin.py` (Step 3), next to the existing trends and coding assertions.

## Done criteria

- [ ] `uv run pytest apps/backend/tests/integration/test_admin.py apps/backend/tests/unit/test_openapi.py -q` exits 0
- [ ] `uv run python apps/backend/scripts/export_openapi.py && git diff --exit-code packages/api-client/openapi.json` exits 0
- [ ] `grep -n "cost_of" apps/backend/src/dotrix_backend/modules/admin/platform.py` shows the helper is used (no price table copied into the admin module)
- [ ] `uv run ruff check apps packages` exits 0, and the TS checks exit 0
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file.
- `AgentRun` has no cached-token column on your base, or `_chat_run` can't set tokens and model — report the helper's signature.
- The grouped queries take more than a second on the test database (a sign the grouping is wrong).

## Maintenance notes

- Costs are computed from today's prices, so a past day's figure changes when a price changes. If history must be stable, store the cost on the run when it finishes (a schema change, deliberately not done here).
- Deferred: latency per provider (record a duration on runs first), and usage per person.
- A reviewer should check that an unpriced model never shows a made-up cost.
