# Plan 046: Kai (the fx fork) becomes Dotrix's fx-slot chat and coding engine

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat HEAD -- packages/engine/src/dotrix_engine/runtimes/fx.py packages/engine/src/dotrix_engine/runtimes/fx_host apps/backend/src/dotrix_backend/modules/agents/fx_pilot.py apps/backend/src/dotrix_backend/modules/coding infra/coding`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live code; on a mismatch in the lines this plan
> changes, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L (spans two repos: `dotrix` and `kai`)
- **Risk**: MEDIUM
- **Depends on**: none
- **Category**: direction / engine swap
- **Planned at**: dotrix `HEAD`, 2026-11-15; kai `main` @ `e332fc7a` (clean mirror of vercel-labs/fx, no fork commits yet). Canonical repo is now `github.com/adeyemiadekunle/kai-engine` (non-fork, so no GitHub "Sync fork"); the old fork `adeyemiadekunle/kai` remains as remote `fork` for reference only — never sync from it.

## Why this matters

Dotrix already runs upstream `fx` in the two places the product needs an
agent engine it doesn't own end to end:

- **Chat**: a person can pick the `fx` runtime for a project conversation;
  Nova on libfx delegates to specialists through the same scheduler
  (`apps/backend/.../agents/fx_pilot.py` + `packages/engine/.../runtimes/fx.py`
  hosting `libfx` in a private Node process).
- **Coding**: `CodingAgent.FX` drives `fx acp` (Agent Client Protocol) inside
  the sandbox image (`infra/coding/fx-acp.mjs`, installed from
  `releases.fx.sh` in `infra/coding/Dockerfile`).

`kai` is a fork of `vercel-labs/fx` now living at `github.com/adeyemiadekunle/kai-engine` (detached from the fork network on 2026-11-15; it had **no custom commits** — a clean mirror of upstream main). The product
direction is to own this engine: rename it to Kai, change what Dotrix needs
(providers, config paths, env vars, release pipeline), and pin Dotrix to the
fork's builds instead of npm `libfx@0.0.16` and `releases.fx.sh`.

Decisions already made with the maintainer:

- **Scope**: replace fx *everywhere* — the `fx` slots in chat and coding run
  Kai. DeepAgents, Claude Code, Codex and OpenCode stay as the other engines.
- **Distribution**: `libfx`-equivalent npm package goes to a **private npm
  registry** under a scoped name; the `kai` coding binary is **built from the
  pinned fork commit inside the Dotrix-built coding image** (no external
  release hosting needed for the binary).
- **Naming**: rename to `kai` — binary `kai`, env `KAI_*`, config `~/.kai/`,
  project `.kai.json`, npm package scoped `kai`. Internal Dotrix identifiers
  that are wire- or DB-visible (`CodingAgent.FX = "fx"`, `DOTRIX_CODING_FX_*`
  env names, `dotrix-fx-*.yaml` egress profiles) keep their `fx` spelling so
  stored settings, journals' external contract and deploy configs don't break;
  comments and docs say Kai.

## Current state

### Chat (libfx host)

- `packages/engine/src/dotrix_engine/runtimes/fx_host/package.json` depends on
  `"libfx": "0.0.16"`; `worker.mjs` does
  `import { createFxAgent, createFxEngine, FxFencedError, memory } from "libfx"`
  and `import { local } from "libfx/durable-local"`, and reads the installed
  version from `node_modules/libfx/package.json`.
- `runtimes/fx.py` `fx_configuration_digest` fingerprints
  `"version": "libfx-0.0.16"`; `FxRuntime.create` refuses to start when
  `fx_host/node_modules/libfx` is missing and tells the operator to
  `npm ci --prefix <fx_host>`.
- `apps/backend/.../agents/fx_pilot.py` pins the runtime binding:
  `_VERSION = "libfx-0.0.16-chat-3"`, `_DURABLE_VERSION = "libfx-0.0.16-delegation-3"`,
  and `_EARLIER` maps earlier bindings to whether their journal is readable
  (`True` = drop and restart the turn). `RuntimeIdentity("fx", _VERSION, …)`
  is recorded on the run (line ~325).
- Journal compatibility is the hard constraint: records written by libfx
  0.0.15 can't be read by 0.0.16; the `_EARLIER` table exists because of it.
  A Kai journal format change needs the same treatment.

### Coding (fx over ACP)

- `infra/coding/Dockerfile` downloads `fx` from
  `https://releases.fx.sh/v${FX_VERSION}/fx-linux-${arch}.tar.gz`
  (`ARG FX_VERSION=0.0.16`), verifies the published SHA-256, installs it as
  `/usr/local/bin/fx`.
- `infra/coding/fx-acp.mjs` spawns `fx acp` (`DOTRIX_FX_BIN` overrides),
  writes `~/.fx/settings.json` each turn (one OpenAI-compatible provider,
  `auto_upgrade: false`), keeps per-session ids under `~/.fx/dotrix/`, sets
  `FX_AUTO_UPGRADE=0 FX_SOUND=0 FX_DISABLE_KEYCHAIN=1 FX_NO_OPEN_BROWSER=1
  NO_COLOR=1`, speaks ACP (`initialize`, `session/new|resume|load`,
  `session/set_mode full-access`, `session/prompt`, `session/update`
  notifications), and forwards the model call through a localhost forwarder
  when `HTTPS_PROXY` is set (fx ignores `HTTPS_PROXY`).
- `apps/backend/.../coding/tools.py`: `CodingAgent.FX = "fx"` (enum value is
  stored in settings/DB — keep it), `FX_DATA = ".fx"` (under `$HOME`, saved
  and restored between turns by `save_state`/`restore_state`),
  `FX_ENDPOINTS`/`FX_PROVIDERS` mirror the chat preview's OpenAI-compatible
  endpoints, `engine_for`/`choose_agent`/`kai_models` pick the engine,
  `settings.coding_fx_model` / `settings.coding_fx_driver`
  (`DOTRIX_CODING_FX_MODEL`, `DOTRIX_CODING_FX_DRIVER`).
- Egress profiles `infra/coding/dotrix-fx-*.yaml` allowlist the model hosts;
  `infra/coding/README.md` documents the image.

### Kai repo

- Zig 0.17+ (`build.zig.zon` pins the toolchain), `zig build` → `zig-out/bin/fx`,
  `zig build libfx-napi -Dnapi-surface=core` → `zig-out/lib/libfx.node`,
  wasm surfaces via `-Dwasm-surface=core|term`.
- `.github/workflows/publish-libfx.yml` builds the NAPI addon per platform,
  packs `libfx` + per-platform packages with `sdk/scripts/package-libfx.mjs`,
  publishes to **npm as `libfx`** — unusable for the fork as-is (name squatting
  and it would publish to the public registry).
- `.github/workflows/release.yml` builds fx binaries for `releases.fx.sh` —
  likewise upstream-owned.
- `src/acp/` is the ACP server dotrix coding drives; `src/core/` owns config
  (`~/.fx/settings.json`, `.fx.json`), sessions (`~/.fx/sessions/`),
  permissions (`FX_PERMISSION_MODE` etc.). `FX_*` env vars and `.fx` paths
  are spread through `src/`; the grep count is large — the rename is the
  biggest single work item.

## Plan

### Phase 0 — Kai fork: rename, version, release pipeline (repo `kai`)

1. **Inventory the rename surface.** `grep -rn "FX_\|\.fx\b\|libfx\|\"fx\"" src/ sdk/ build.zig`
   and produce a mapping table before editing: binary name, env prefix
   (`FX_` → `KAI_`), home dir (`~/.fx` → `~/.kai`), project file
   (`.fx.json` → `.kai.json`), session root, package name `libfx` → scoped
   `kai` name, ACP `clientInfo`/server names, `--version` string.
   Decide and record: npm scope (suggest `@dotrix/kai` or the org's scope —
   confirm with maintainer before publishing), whether old `FX_*`/`~/.fx`
   are read as fallbacks during transition (recommend **no**: clean break,
   dotrix pins both sides together).
2. **Rename in `src/`**: user-visible strings, env vars, paths, command
   name. Keep internal Zig module/file names (`src/acp`, `src/core`) unless
   they leak into output. `zig fmt src/` after edits; `zig build test`.
   ACP wire protocol (`session/*` methods, `session/update` shapes) must
   stay byte-compatible — dotrix's `fx-acp.mjs` depends on it; add/adjust
   tests rather than weakening them.
3. **SDK/package**: `sdk/package.json` name → the scoped name; keep export
   subpaths (`./durable-local` etc.) identical so `worker.mjs` changes are a
   one-line import rename at most. `sdk/scripts/package-libfx.mjs` — rename
   script/package output names accordingly; check `sdk/tests/` still pass
   (`npm ci --prefix sdk/node`, `node --experimental-wasm-jspi` core tests).
4. **Versioning**: Kai versions as `<upstream-base>-kai.<n>` (e.g.
   `0.0.17-kai.1`) or independent semver — pick one and encode it in
   `build.zig`'s `app_version`/`update_channel` path; the version must be
   recoverable from `kai --version` and the built `libfx` package.json.
5. **Workflows**: replace/disable `publish-libfx.yml` and `release.yml`
   (they target upstream's npm name and `releases.fx.sh`). Add
   `publish-kai.yml`: matrix over platforms, `zig build libfx-napi`,
   `sdk/scripts/package-libfx.mjs` into the scoped name, `npm publish` to the
   private registry (GitHub Packages or the org's registry — needs
   `NPM_TOKEN` secret; STOP if registry choice is undecided). Also build
   `kai` binaries (linux x64/arm64, macOS arm64) and attach to a GitHub
   Release **or** keep binaries source-built only (Phase 2 builds in the
   image anyway — binaries release optional, do it only if dev machines
   need prebuilt kai).
6. **Kai repo verification** (its AGENTS.md is strict): `zig build`,
   `zig build test`, `zig fmt --check src/`, `zig fmt src/`,
   `scripts/check-*-boundary.sh` all pass, run the built binary
   (`zig-out/bin/kai`) through one real interaction, and CI green including
   macOS arm64 before calling the fork ready.

### Phase 1 — Dotrix chat on Kai libfx

7. `fx_host/package.json`: `"libfx": "0.0.16"` → the scoped Kai package at
   the pinned version; `npm install --package-lock-only` (or `npm install`)
   in `fx_host` and commit `package-lock.json`. Configure `.npmrc`/CI for the
   private registry (GitHub Packages needs auth even for reads in CI —
   STOP and ask maintainer for the token story if none exists).
8. `worker.mjs`: update the `libfx` import specifiers to the scoped name;
   keep `createFxAgent/createFxEngine/FxFencedError/memory` and
   `durable-local` usage identical (Kai keeps the same JS API — verify
   against `sdk/engine.js` exports in the kai repo; if renamed, adapt).
9. `fx.py`: `"version": "libfx-0.0.16"` in `fx_configuration_digest` → the
   Kai version string; the missing-package error message names the new
   package. Local-session digest changes are fine (they only guard reuse of
   a local dir).
10. `fx_pilot.py`: `_VERSION`/`_DURABLE_VERSION` → e.g.
    `"kai-<ver>-chat-3"` / `"kai-<ver>-delegation-3"`; extend `_EARLIER` so
    every `libfx-0.0.16-*`/`libfx-0.0.15-*` binding maps to `True` (journal
    unreadable → fresh turn) **unless** Kai's journal format is verified
    compatible — verify by reading kai's journal/checkpoint code
    (`src/core/agent/runtime/checkpoint.zig`, `src/acp/libfx_journal.zig`)
    and, if unchanged, still treat as incompatible unless a test proves
    otherwise. `RuntimeIdentity("fx", …)` — decide: keep `"fx"` (audit log
    continuity) or `"kai"`; recommend `"kai"` since people never see it and
    audit clarity matters. Check everywhere `RuntimeIdentity`/`"fx"` is
    matched (grep `RuntimeIdentity`, `agent_runtime` identity checks).
11. Tests: `test_fx_changes.py`, `test_runtime_tools.py`,
    `test_specialist_continuity.py`, `test_chat_inputs.py` reference
    `libfx-0.0.16*`; update fixtures/parametrizes. Integration tests need the
    real package — `npm ci --prefix fx_host` must work in CI with registry
    auth.

### Phase 2 — Dotrix coding on Kai binary

12. `infra/coding/Dockerfile`: replace the `releases.fx.sh` download with a
    multi-stage build: `FROM` a Zig 0.17 toolchain image (or install zig
    pinned by version+sha256), clone `github.com/adeyemiadekunle/kai-engine` at a
    **pinned commit SHA** (`ARG KAI_COMMIT`), `zig build -Doptimize=ReleaseSafe`,
    install `zig-out/bin/kai` as `/usr/local/bin/kai`. Keep the sha256
    verification habit — pin `KAI_COMMIT` and verify `kai --version`
    contains the expected Kai version. Network note: the image build needs
    github.com + ziglang.org reachable at build time (same as today's
    releases.fx.sh).
13. `fx-acp.mjs` → rename file to `kai-acp.mjs` (update `coding_fx_driver`
    default and `Fx.driver` default `/opt/dotrix/kai-acp.mjs`): binary
    `kai` (`DOTRIX_KAI_BIN` env, keep `DOTRIX_FX_BIN` as fallback for one
    release), `~/.kai` instead of `~/.fx` (`KAI_HOME` if Kai supports an env
    override — check; else keep `homedir()/.kai`), `KAI_*` env vars matching
    the Phase-0 rename, settings file format per Kai's renamed config
    (`providers`/`models`/`auto_upgrade` keys — re-verify against
    `src/core/config` in kai), ACP calls unchanged. Egress forwarder logic
    unchanged (Kai must still ignore `HTTPS_PROXY` the same way — verify;
    if Kai honors proxies now, simplify but keep the localhost-HTTP trick
    working).
14. `tools.py`: `FX_DATA = ".fx"` → `".kai"` (save/restore state); update
    comments (`0.0.16` → Kai version); keep `CodingAgent.FX`,
    `coding_fx_model`, `coding_fx_driver`, `DOTRIX_CODING_FX_*`,
    `dotrix-fx-*.yaml` names (stored values); driver default path →
    `/opt/dotrix/kai-acp.mjs`. Check `session.set_mode` mode id `full-access`
    still exists in Kai (permissions rename may change mode ids — STOP if
    the ACP surface changed).
15. Tests: `test_fx_coding.py` (fake ACP server — update paths/env names),
    `test_coding.py` (`'0.0.16'` fixture → kai version string),
    `infra/coding/mcp-check.mjs` if it references fx paths.

### Phase 3 — docs, CI, rollout

16. Update `CLAUDE.md` (fx→Kai engine descriptions, versions),
    `docs/engine.md`, `docs/nova-team.md`, `infra/coding/README.md`,
    `AGENTS.md` summaries where they name libfx/fx versions.
17. CI: engine test jobs run `npm ci --prefix packages/engine/.../fx_host`
    — must authenticate to the private registry (repo secret → `.npmrc`).
    Docker image build job builds kai from source — needs `KAI_COMMIT`
    available; consider a `kai-ref` file or repo variable.
18. Rollout: chat bindings are per-run; old `libfx-*` bindings fail closed →
    `_EARLIER` restart path covers them. Coding sessions save `~/.kai`
    state going forward; in-flight sessions with `~/.fx` state: the first
    Kai turn finds no saved session and starts fresh (driver already emits
    `fresh` when resume fails) — acceptable, note in changelog.
    `pnpm openapi` only if API-visible strings changed (they shouldn't).

## Verification

- Kai repo: `zig build`, `zig build test`, `zig fmt --check src/`, boundary
  scripts, real `kai` binary run, CI green (incl. macOS arm64).
- Dotrix: `uv run ruff check apps packages`, `uv run pytest`
  (esp. `test_fx_changes.py`, `test_fx_coding.py`, `test_runtime_tools.py`,
  `test_coding.py`), `pnpm format:check && pnpm lint && pnpm build &&
  pnpm typecheck && pnpm test && pnpm knip`; `pnpm openapi` only if the API
  changed.
- Live smoke (before calling ready): one fx-runtime chat turn end-to-end,
  one coding turn through the Kai ACP driver against a fake or real
  provider, a killed-worker recovery of an fx chat run, resume of a coding
  session.

## STOP conditions

- The private npm registry isn't decided or has no CI credential path.
- Kai's rename would break ACP/journal wire compatibility dotrix depends on
  (protocol shapes, `session/update` variants, journal record format) and
  the fix isn't a mechanical rename.
- `zig` toolchain version required by kai's `build.zig.zon` can't be pinned
  reproducibly for the Docker build.
- Any stored identifier (`CodingAgent.FX`, `coding_agent="fx"`, journal
  `RuntimeIdentity`) turns out to be user-visible in the web UI — people
  must keep seeing only "Kai", never the engine.
- Merge cost: if the fork already diverged from upstream in ways that make
  the rename conflict-heavy, re-scope Phase 0 before editing.
