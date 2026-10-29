# Chat runtime experiment

This is an isolated, read-only experiment for comparing the engine's new
`DeepAgentsRuntime` and `FxRuntime`. It is not wired into the API, workers, or the
production conversation runner. It creates in-memory conversations using the built-in
roles and instructions from `dotrix_engine.builtins`. Both runtimes receive the same
scenario, instructions, evidence, model choices, and host-provided `read_evidence`
tool. DeepAgents' other tools are hidden and rejected.

The default scenario asks Nova to recommend which specialists to consult, gives Orion
an analysis and a follow-up in the same session, then asks Nova to synthesize Orion's
outputs. The default sequence is **scripted**, not dispatched by Nova. The optional
`--delegate` mode instead gives Nova a host-owned `delegate_tasks` tool that runs
read-only specialists, using Dotrix's batch and result schemas. Its in-memory scheduler
is an experiment, not the platform's delegation service. Specialists must submit a
structured result; a missing result is partial and blocks dependent tasks. The result
is held only in memory and its factual claims are not independently verified.
Either runtime can have different prompt overhead and model behavior. The DeepAgents side uses `create_deep_agent` with the
built-in role instructions, not the complete production `build_team` configuration.

## Run

Requirements: Node 20.19 or 22.12+, Python 3.11+, uv, and an OpenAI Chat
Completions-compatible endpoint. Both sides use the *same* endpoint, model IDs, and
API key. libfx accepts HTTPS, or HTTP for localhost. The sample contains only synthetic
data. Do not put real project information here unless the endpoint and local machine
are authorized to receive it: scenario contents and model responses are sent to the
endpoint, and the JSON output includes the responses.

```sh
uv sync --package dotrix-engine
npm ci --prefix packages/engine/src/dotrix_engine/runtimes/fx_host
export DOTRIX_EVAL_BASE_URL=https://your-provider.example/v1
export DOTRIX_EVAL_MODEL=your-model-id
export DOTRIX_EVAL_API_KEY=your-api-key
uv run --package dotrix-engine python experiments/fx-chat/run.py --runtime both > /tmp/dotrix-eval.json
uv run --package dotrix-engine python experiments/fx-chat/run.py --runtime both --delegate > /tmp/dotrix-team-eval.json
```

For a local endpoint that needs no key, omit `DOTRIX_EVAL_API_KEY`. Use `--runtime fx`
or `--runtime deepagents` to run one side; `--scenario path/to/case.json` selects a
different case. A scenario can have a `models` object mapping built-in handles to model
IDs, for example `{"architecture": "other-model"}`; all models must be served by the
same endpoint. Alternatively, configure named tiers in the scenario:

```json
{
  "model_policy": {
    "default": "economy",
    "tiers": {
      "strong": { "model": "your-strong-model" },
      "economy": { "model": "your-cheaper-model" }
    },
    "agents": { "project-manager": "strong", "architecture": "strong", "research": "economy" }
  }
}
```

Add `model_policy` to a complete scenario; when present it takes precedence over
`models`. Both model IDs must be available through the configured endpoint.
For the delegation experiment, a host-provided `task_tiers` object can assign a tier
to a task key. Task keys and agent requests come from the model; this mapping is only
a routing experiment, not a budget, authorization, or protection against a model
choosing an expensive route. The platform must enforce those separately. `--delegate`
records parent and specialist usage where the provider reports it. Actual savings
depend on model pricing and whether quality remains adequate.

Each scripted turn can refer to earlier turn IDs in `include`, which appends those
actual outputs to its prompt. Review the
results: the JSON records each reply, tool names, wall time, model, stop reason, and
provider-reported input/output tokens when available. Missing usage is `null`, not
zero. It does not estimate cost; apply the provider's pricing, including cache and
reasoning charges where applicable. Single runs and differing prompts are not a fair
basis for ranking models or frameworks.

To run the deterministic integration tests, which use the actual libfx and
DeepAgents runtimes against a local fake model server:

```sh
uv run --package dotrix-engine python -m unittest discover -s experiments/fx-chat -p 'test_*.py' -v
node --test packages/engine/src/dotrix_engine/runtimes/fx_host/handoff.test.mjs
```

## What this does and does not establish

- The two runtimes can run separate Nova and specialist conversations, call a common
  read-only tool, and reuse a specialist's context for a follow-up. The tests also
  check that another role does not inherit that context and that unknown evidence
  names cannot read local files.
- The default in-memory stores end when this process ends. `FxRuntime` also has an
  explicitly configured local session store: tests reopen a conversation after a
  host restart and resume an interrupted turn. It supports streaming and steering
  within a running process. None of these features is connected to Dotrix's UI or
  platform recovery, approvals, MCP, skills, or workspace access.
- `FxRuntime` can use the AI Gateway directly, including an optional effort setting.
  The comparison CLI uses an OpenAI-compatible custom endpoint, for which this
  adapter rejects an effort setting; it never silently ignores one. DeepAgents can
  receive a model configured with provider-supported reasoning options. The model
  policy resolves a choice, but does not itself change a running session's model.
  In the delegation experiment, the same specialist routed to a different model
  gets a separate in-memory session, so its previous conversation is not reused.
- No platform policy, data, credentials, agent run, or existing DeepAgents behavior
  is modified. Do not deploy the bridge as a service or use it for production data.
- The canned local model tests check integration and selected local recovery mechanics,
  not model quality, real provider compatibility, token cost, safety against prompt
  injection, or distributed platform recovery.

See [the runtime evaluation design](../../docs/chat-runtime-evaluation.md) for the
proposed integration boundaries, comparison method, and rollout gates.
