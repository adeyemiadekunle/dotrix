# Measuring Nova's Code Mode

`tests/integration/test_live_scripts.py` contains a small live smoke comparison and
an explicitly enabled benchmark. Both use real Nova runs through the API, on
DeepAgents and fx, with the requester's provider key. They do not change the
deployment default or expose new tools to scripts.

Settings → Preferences → Code Mode saves a personal preference through
`GET/PUT /v1/me/code-mode`. It defaults to allowing scripts when the server enables
them; `DOTRIX_AGENT_SCRIPTS` remains off by default on deployed servers. Disabling
the personal preference removes `run_script` and its guide from new Nova turns on
both runtimes. The choice is pinned on the run at first execution; approval waits
and retries keep their tools. fx also retains its existing encrypted binding
snapshot, including for runs bound before this preference was introduced.

## Run a comparison

Use the normal integration-test Postgres setup. Install the optional fx host to
test fx. Set only the provider key you intend to use:
`DOTRIX_LIVE_NVIDIA_API_KEY`, `DOTRIX_LIVE_ANTHROPIC_API_KEY`, or
`DOTRIX_LIVE_OPENAI_API_KEY`. Provider calls may incur charges.

For a bounded first run (one runtime, model, workload and strategy; four turns):

```bash
DOTRIX_LIVE_SCRIPT_BENCHMARK=1 uv run pytest \
  apps/backend/tests/integration/test_live_scripts.py \
  -k 'test_live_script_benchmark and deepagents-nvidia and filter and natural' \
  -s --basetemp=/tmp/dotrix-code-mode-benchmark
```

`--basetemp` is pytest-owned and is cleared on reuse: choose a dedicated directory.
Every benchmark case writes `code-mode-benchmark.json` in its pytest temporary
directory and emits one `CODE_MODE_BENCHMARK` JSON line. Reports retain measurements,
not tool content, answers or credentials. Keep the stdout JSON lines to aggregate
multiple invocations.

Without the explicit benchmark flag the larger cases are skipped, even when a
live key exists. The older smoke comparisons remain key-gated. Running the whole
new matrix means 36 cases, each with four turns by default (144 turns if every
provider and runtime is available). Select cases deliberately.

## Workloads and trial design

- `tiny-control`: the existing five tiny files. Little intermediate data can be
  discarded, so an overhead regression here is expected and useful to measure.
- `filter`: three large documents containing 300 support records. Select only
  records whose structured topic is `refund` and status is `blocked`. Distractors
  satisfy only one predicate. Answers must contain exactly the three expected
  IDs, in order, with no extra or duplicate IDs.
- `dependent`: first read an index, then the documents it names, and apply the
  same filter. The index is the dependency; its evidence paths must be discovered.

Each workload runs in `natural` and `requested` strategies. Natural trials use
identical prompts with scripts available or unavailable. Requested trials ask for
`run_script` when available and ordinary tools otherwise. This is an instructed
comparison, not provider-enforced tool selection. A model ignoring the instruction
is recorded as non-adoption, not a successful script benchmark.

Every trial starts a fresh conversation. The immutable corpus is identical within
a comparison. The default is two pairs, ordered on/off, then off/on.
`DOTRIX_LIVE_SCRIPT_REPEATS` accepts even counts from 2 to 10; repeat pairs alternate
order. This balances position but does **not** reset a provider cache or establish
statistical significance. Run providers and runtimes separately if comparing cache
behavior; shared prompts can warm caches across cases.

## Read the measurements

Each trial records answer correctness, completion status, wall time including the
API turn, script invocations and successful nested reads, successful tool-result
bytes crossing the runtime boundary, model calls, input/output tokens, cache-read
tokens, derived uncached input, and the runtime's usage-completeness indicator.

The byte counts use UTF-8 content or JSON serialization. DeepAgents is observed at
its tool-end callback, excluding nested reads inside a script; fx is observed at
its successful outer `tool_reply` sends. Script read bytes measure successful raw
results before filtering. These are content-volume diagnostics, **not** exact
provider tokens, HTTP bytes, or the sum of context re-sent on later model calls.
Errors, handoffs, later runtime formatting and truncation are excluded. Bytes from
different runtime serializers are not directly equivalent. No content is logged.

Inspect both script adoption and correctness before comparing savings. Report
natural and requested trials separately. Reject incomplete usage for cost claims;
retain incomplete and failed-quality trials rather than silently selecting the
best runs. Unknown cache counts stay unknown. There is no assumed dollar saving:
apply the provider/model's current input, cache and output prices separately, with
cache-write pricing where applicable. The report does not calculate billed cost.

The benchmark tests execution overhead and filtering behavior; it does not prove
deployment readiness, citation quality, or behavior on arbitrary project data.
The sandbox, permission and approval regression suites remain separate.
