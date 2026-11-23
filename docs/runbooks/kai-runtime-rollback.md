# Kai Runtime Rollback Runbook

Use this procedure to halt new `fx` admissions and return new Chat and Code work to legacy defaults while preserving active sessions and recovering in-flight runs safely.

## 1. Symptoms Triggering Rollback

- Elevated failures, crashes, or stalled runs scoped to `chat_runtime="fx"` or `CodingAgent.FX` (`fx` / `libfx`).
- Regressions in tool approvals, journal recovery, ACP `fx-acp.mjs`, or sandbox isolation after a runtime upgrade.

## 2. Immediate Switches (Stop New `fx` Admissions)

Set the following environment variables on the API and worker services and restart them:

1. **Chat runtime rollback** (`DOTRIX_CHAT_DEFAULT_RUNTIME`):

   ```bash
   DOTRIX_CHAT_DEFAULT_RUNTIME=deepagents
   ```

   - New interactive project Chat conversations route to `DeepAgents` instead of `fx`.
   - Existing Chat threads remain pinned to their recorded `chat_runtime` so active histories and pending approvals recover without mixing runtimes.

2. **Code engine rollback** (`DOTRIX_CODING_AGENT`):

   ```bash
   DOTRIX_CODING_AGENT=legacy
   ```

   - `engine_for` and `choose_agent` omit `CodingAgent.FX` from automatic fallback, routing Anthropic models to `claude-code`, OpenAI models to `codex`, and other providers to `opencode`.
   - Existing coding sessions remain pinned to their recorded `CodingSession.agent` and `profile_digest`.

3. Optionally pause unattended scheduled runs while investigating (`pause_unattended` / Admin console) if scheduled runs were pinned to `fx`.

## 3. Drain & Recover Active `fx` Runs

1. **Do not delete `.fx` state or `agent_runtime_calls`:** Keep the existing `@kunemi-group/kai` host package (`LIBFX_ARTIFACTS`) and coding image installed so active `fx` conversations and sessions finish or recover on their recorded runtime.
2. **Chat runs:** Let worker lease expiry / recovery sweep resume interrupted `fx` attempts through `AgentRunner`. Recorded side-effecting tool results in `agent_runtime_calls` are replayed once (`rerun_tools` skips completed mutations); verify any pending inbox approvals are decided or explicitly rejected before retrying.
3. **Code runs:** Let active coding leases finish or settle via `expire_coding_leases` and `recover_uncertain_runs`:
   - If a commit/push landed on GitHub, reconciliation adopts the branch/PR without re-running `fx`.
   - If nothing was pushed or a warm sandbox failed health checks, close the warm sandbox and retry or let the user start a follow-up session under legacy engines.
4. **Reconcile unknown tool outcomes:** Audit `agent_runtime_calls` rows with `status="uncertain"` (or coding runs in `recovery_required`) before manually retrying mutations so writes are never double-applied.

## 4. Verification After Rollback

- Start a new interactive project Chat conversation -> confirm `run.chat_runtime == "deepagents"`.
- Start a new Code session -> confirm `agent` resolves to `claude-code`, `codex`, or `opencode` (not `fx`).
- Reply on an existing `fx` Chat conversation -> confirm it resumes cleanly on `fx` without `RuntimeLocked` conflicts.
- Run automated rollback regression checks:
  - `uv run pytest apps/backend/tests/unit/test_coding.py -k legacy`
  - `uv run pytest apps/backend/tests/unit/test_fx_pilot.py -k rollback`
