# Evaluating libfx for the Dotrix chat team

Dotrix owns Nova, Lyra, Orion, Vega, Juno and Echo, their instructions and policies,
and the lifecycle of their work. DeepAgents and libfx are candidate execution
engines underneath those identities. Kai remains in the coding service. The
read-only [experiment](../experiments/fx-chat/README.md) compares role conversations
and host-controlled delegation. The experimental runtime implementations are in
`dotrix_engine.runtimes`; they are not production adapters or evidence that either
framework wins.

The read-only team experiment validates `SpecialistBatch` and `SpecialistResult`,
requires a specialist to submit a structured result, and blocks a dependent task
when its prerequisite is partial or blocked. Tasks targeting the same specialist
session are serialized so their results cannot be attributed to each other. These
results and scheduler state are still in memory, not the production task tree.

## Integration boundary

The Python platform currently builds a LangGraph agent in `agents/runner.py`, streams
its graph events, and resumes LangGraph interrupts for approvals and delegation.
libfx is a JavaScript library: using it in the platform requires a host process and
an authenticated, versioned protocol, not a Python import or a change of model name.
Keep the existing DeepAgents path as the default while experimenting.

A useful runtime boundary would represent starting and resuming a turn, observing
events and usage, steering, cancellation, and capability discovery. Do not promise
that every runtime supports every operation: define unsupported, accepted, completed,
and failed outcomes explicitly. Separate a product `AgentRun` and Dotrix's task tree
from a runtime session and an individual turn. A runtime event needs run, agent,
session, turn, attempt and ordering identities; avoid treating best-effort SDK hooks
as a durable event outbox. Store runtime type, pinned version and session mapping with
the run so that a restart or configuration change cannot resume it through a
different engine by accident.

The first boundary provides session creation, prompt/result, streaming, cancellation,
capability discovery, and explicit unsupported-operation failures. `FxRuntime` also
exposes in-process steering and optional local persistence and resume;
`DeepAgentsRuntime` accepts a caller-configured model but cannot steer or resume an
interrupted turn through this prototype interface.
The fx host is a private Node subprocess and calls tools back in Python. These
implementations advertise no platform crash recovery or approval support. An optional scoped tool handler
receives the runtime's session ID and, on fx, its execution ID. These are correlation
data, not verified workspace, user, run or lease authority. A production integration
must bind verified execution context and recheck authorization and fencing for every
effect.

Project Chat now exposes host-owned steering and ordered queued follow-ups for both production runners. DeepAgents injects a stable-ID human message before the next model call; fx uses its active-turn steering API with a stable input ID. A queued follow-up becomes a normal run only after the current turn completes, with current access and approval checks. Inputs persist independently of the web connection; cancellation applies before delivery, and Stop cancels pending inputs. Runtime acceptance does not prove model placement or task completion. Only resumable DeepAgents model-limit/interrupted failures keep queued follow-ups waiting; fx failures reject them. DeepAgents failure handling checks restored checkpoint messages (including delta history) before rejecting steering, leaving delivery unconfirmed if restoration is unavailable. Steering does not propagate into already-running specialist tasks or bypass an approval wait. Cross-project conversations retain their existing single-active-turn behavior. The isolated `DeepAgentsRuntime` prototype still advertises steering as unsupported; the platform implements it through host middleware and scheduling.

An experimental backend adapter, `agents/runtime_tools.py`, wraps the existing
project knowledge reads in host-owned runtime tools. It checks the bound session,
workspace, project, requester, run status, lease and current agent permissions both
before and after a read. Integration tests exercise both runtimes against real project
knowledge and verify revocation and stale leases. `agents/runtime_sessions.py` now
persists one session binding per run, pins runtime type, version and configuration,
and only admits a running, leased run with current project access. Competing bindings
are serialized or rejected by database constraints; a new attempt can retrieve the
same binding after it acquires a new lease. Tool calls must match the persisted binding.
The binding alone does not persist a journal or grant delegation and approval
contracts; the separately gated journal integration below builds on it.

This initial binding deliberately does not reuse a session across runs: a runtime
session ID belongs to one run. Reusable specialist conversations need a separate
explicit ownership and concurrency model. The trusted host must derive the stored
fingerprint from the actual configuration, isolate runtime storage per owner, and
version its tool implementations and policies. `fx_configuration_digest` produces
the same public-settings digest as the local fx store; it does not hash tool code or
credentials. Authorization and the lease still need checking at every external effect.

`agents/fx_pilot.py` composes the binding, scoped reads and (through `agents/fx_tools.py`)
approved changes for an opt-in Nova conversation. It obtains the selected model, fixed provider
endpoint, requester's personal key, built-in role and current guidance from an admitted
run. It checks access and the lease before forwarding each runtime event and before
returning the answer. Real-Postgres tests with a local fake model check the role, key,
project read, duplicate refusal, and mid-turn membership or lease revocation.

The pilot runs interactive Nova turns in every work mode (2026-10-30), with no token
budget and no automation. Its changes use DeepAgents' builders and approval rules: a change that
asks saves a pending approval and hands the turn off, and the decided call resumes from the journal
with its approver, or hears the rejection. Each change is claimed before it runs and its result saved
after (`agent_runtime_calls`), so a recovered turn never changes the project twice; a call cut off
between the two is reported as such, not retried. Every turn is journaled, so the dispatch sweep's
recovered attempts and Continue resume it. Delegation, project-changing tasks included, requires a separate flag. It supports the configured
OpenAI-compatible provider endpoints, Anthropic's included (its OpenAI-compatible endpoint, checked live on
Claude Haiku 5.5 on 2026-10-30: tools, follow-ups, steering, a journal reopened and a retry answered from it, and
`test_live_fx_chat_on_anthropic_reads_project_knowledge` through the public API when given
`DOTRIX_LIVE_ANTHROPIC_API_KEY`); not Google's API. The `experiments/fx-chat` comparison also ran on Claude Haiku 5.5
through that endpoint (2026-10-30): the scripted scenario and live delegation finished on both runtimes, with the same
specialists chosen, the same recommendation, and similar caveats (one run each, not a ranking). The delegation team now
names the evidence documents in its instructions; without them both runtimes guessed paths and found nothing. A run bound to an older pilot version (in-memory or read-only) fails closed rather than resuming on this one.
The platform runner persists replies and events, and passes bounded recent history to
later turns. It records available usage and marks unreported usage incomplete. The selector
needs no switch (2026-10-30: `DOTRIX_FX_CHAT_PILOT` was removed); new
conversations default to DeepAgents and remain pinned to their selected runtime. It shares the context pack,
workspace rules, board tools and approvals with DeepAgents; it does not yet have reusable specialist sessions,
token budgets, or recovery proven across distributed workers on real models.

For native development, install Node 22 and run
`npm ci --prefix packages/engine/src/dotrix_engine/runtimes/fx_host` before enabling
the preview. The production backend image includes Node and the pinned fx host.
Development Compose mounts the engine source from the host, so it also needs the
host-side `npm ci` when the preview is enabled.

### Durable read-only delegation preview

Set `DOTRIX_FX_CHAT_DURABLE_DELEGATION=true`
on the API and worker to opt new fx runs into durable delegation. The run records
that choice; disabling the flag does not change an existing run's recovery
contract. Nova may selectively ask built-in specialists for read-only work through
Dotrix's existing `DelegationService`. Children keep their existing isolated
DeepAgents checkpoints, structured results, dependency rules, requester permissions,
personal credentials, and project specialist model/per-agent overrides. Native fx
subagents do not create another task tree. This allows a stronger Nova model and
cheaper specialist models using the existing settings; automatic importance-based
routing, budget enforcement and measured cost savings remain open.

`agents/runtime_journal.py` stores encrypted opaque records and checkpoints in
Postgres, bound to one run and runtime configuration. Every operation rechecks
workspace, requester access, run status, current lease and configuration. A run-row
lock serializes appends with lease acquisition, and expected cursors fence competing
journal writers. Idempotent retries must match the original bytes and expected
cursor. Records are limited to 2 MiB and the whole journal plus checkpoint to 8 MiB;
exceeding the limit fails the turn. Run deletion cascades to the journal. This is
per-run durability, not a reusable private specialist conversation.

A stable fx tool execution ID identifies the specialist batch. Dotrix stores an
encrypted canonical brief with child creation in one transaction; a retry must
match that brief before it can reuse the children or their saved results. The host
then cancels the fx turn with a handoff marker, closes the subprocess, and moves the
parent into `waiting_children`, releasing its worker. The scheduler runs children
and queues the parent when results are ready. A fresh fx process reloads the journal
and replays only explicitly permitted read tools and the verified delegation call.
The prompt's stable message ID is the run ID. Child creation and parent waiting are
separate transactions: a crash between them relies on the existing expired-lease
recovery and the saved batch to retry safely. Failed/cancelled fx parents cancel
unfinished children; the team sweep repairs a lost completion callback or a parent
failed by the lease sweeper, rechecking its locked status before cancellation. Expired workers cannot renew their lease or clear the expiry
that the recovery sweeper needs.

The low-level libfx engine currently returns no saved answer text when replaying an
already committed turn. The host therefore has a deliberately narrow compatibility
reader for **libfx 0.0.16**, **libfx-journal-v1**, extracting only committed successful
assistant output. It rejects unknown formats and package versions. Truncated,
interrupted or refused turns cannot become a successful reply on replay. Automatic
checkpointing is set above the journal quota to retain the full record history that
this reader needs; historical records are not compacted. This private-format
dependency must be retested on SDK upgrades and replaced when a suitable public
result-history API is available. A turn restored from an existing journal marks
usage incomplete, since pre-crash or pre-handoff usage may be absent; it does not
claim zero cost. Previously delivered streaming events may be repeated across
attempts; they are observations, not an exactly-once event contract.

Real-Postgres tests kill the fx host during a read and after specialist child creation
before handoff acknowledgment. A new process recovers the same execution ID without
duplicating children. Tests also cover competing appends, stale leases, revoked
membership, encryption, quota failure, changed-brief rejection, completed-output
recovery and unsuccessful-answer replay. An API integration runs a real fx Nova,
the real scheduler and a real DeepAgents child runner with a scripted model, and
checks its cheaper specialist model and saved result. The older in-memory probe and
Node handoff test remain useful SDK checks. These synthetic-provider tests do not
establish paid-provider quality/cost, all distributed failure windows, or production
readiness. Streaming, Stop and existing Agents activity use the normal run ledger;
steering and queued follow-ups use private product APIs and delivery authorization.

### Local fx sessions

The prototype can opt into `FxRuntime.create(..., local_dir=Path("/absolute/private/path"))`.
Create a session with `await runtime.new_session()`, retain that returned ID, and
later reopen the same runtime configuration and use `prompt()` or `resume()` with
it. A caller can provide a stable `message_id` to avoid running the same prompt
twice. The caller must also bind that ID to the original input: a repeated ID is not
proof that a later request contains the same text. For an already completed retry,
the wrapper reconstructs the prior text and tool names from libfx's session stream
and sets `TurnResult.repeated`; those historical events are not delivered again to
the live event callback. `turn_accepted` is an observation, not a Dotrix transactional
outbox or a persistence barrier for the caller.

The directory must be private and owned by the process user on POSIX. On first use,
it is bound to a fingerprint of the runtime version, agent, instructions, model,
provider and tool definitions; a different configuration is rejected. The caller
must still create separate storage and check authorization for each workspace,
person, project and conversation. Local session contents are not encrypted by this
adapter, need retention/deletion handling, and live only on that filesystem. Changing
configuration or model requires a new store; migration is not implemented.

Controlled process-kill tests show that libfx can continue a locally stored turn,
replay a tool declared idempotent with the same execution ID, and decline automatic
replay of a non-idempotent interrupted call. A later model decision can still ask for
a new call. For an idempotent write, the service doing the write must actually
deduplicate it using a scoped key such as session plus execution ID; marking a tool
idempotent alone does not make its effects safe. These tests do not establish the
distributed lease, fencing, authorization, event delivery or approval guarantees
needed by the platform. The runtime therefore does not advertise platform crash
recovery.

`ModelPolicy` resolves host-configured tiers by agent or a host-selected task tier.
This lets a caller route Nova or an important specialist to a stronger model and a
routine task to a cheaper one. Project settings expose a shared specialist model
and a default per-run token budget. For scheduler-owned specialists under either Nova
runtime, the model is pinned at task creation in this order: a personal agent model,
project/workspace agent override, shared specialist model, conversation model, then
project model. Existing unpinned tasks resolve when they start; personal provider keys
are checked at execution. Changing project model settings is audited. Agent-specific
budgets override the project default, and the check before a model call can allow the
limit to be exceeded by that call. The fx Nova preview still refuses a project budget.
A routing policy alone
does not enforce an allowed-model list, budgets, provider credentials or cost limits;
those remain platform responsibilities. The policy does not automatically assess
importance, and SDK/model support for reasoning effort must be checked rather than
silently assumed.

The integration test `test_delegated_specialists_use_their_model_override_or_project_default`
checks the current runner with actual delegated child runs: a project-wide specialist
model handles one child, while another specialist's configured model takes precedence.
Neither that test nor the synthetic fx comparison measures real provider cost or
decides how a task's importance should select a tier.

Dotrix must remain the authority for the workspace and requester, model-key choice,
the resolved agent contract, tool permissions, approvals, audit, usage budgets, and
the delegation scheduler. The host must derive these from the run, never trust model
arguments or a runtime session ID as authorization. A child gets no more authority
than its requester and parent, and cannot delegate. Keep the existing two-reader
concurrency limit, serialized project-changing tasks, task dependencies, persisted
structured results and blocked-dependent behavior. In particular, fx native
subagents must not bypass `DelegationService` or create a second task tree.

libfx's session journal can preserve a prompt and steps, but a tool interrupted
after a side effect is ambiguous. Dotrix's lease and fencing token must be checked
at every external effect; a runtime journal is not permission to replay a write.
Keep Dotrix's outbox, approvals and idempotency/settlement rules until an integration
proves equivalent behavior under process death, duplicate delivery and stale workers.
Mark a tool idempotent only when its *actual* effects can safely be repeated, and
test ambiguous non-idempotent operations explicitly. Version and secure session
storage, verify ownership before every prompt, stream, steer or cancellation, and
plan for SDK checkpoint incompatibility and rollback.

## Specialist continuity

`DOTRIX_SPECIALIST_CONTINUITY=true` enables a limited private continuity preview
for read-only specialist tasks from an interactive project conversation, whether
Nova runs on DeepAgents or fx. Set it on the worker and API; it is off by default.
The session identity is the workspace, project, requesting person, parent chat
thread and built-in specialist. Another person, chat thread, project or specialist
gets a different session. Automations, coding outcomes and tasks that may change
project data do not use this feature.

Each task keeps its own LangGraph checkpoint. The session stores metadata and the
scheduler selects up to eight earlier **completed** briefs, replies and structured
results; the task stores their run IDs when it is queued, so retries select the
same history. The input is capped at 24,000 characters after escaping and is passed
to the specialist as untrusted evidence with a reminder to recheck stale project
facts. Failed, blocked and partial work is excluded. A fingerprint records the
specialist’s permissions and the requester’s role and workspace permissions at
queue time. History is selected only when that fingerprint matches, and the worker
checks it before and after reading. A result is not reused if permissions at task
completion differ from those at queue time. A change while a task is queued fails closed; model changes do not
reset history by themselves. This is bounded continuity of committed work, not the
complete model/tool transcript or a native long-lived fx specialist session. A new chat thread starts new specialist histories.

The scheduler serializes queued, running and approval-waiting tasks sharing a
session, including across parent runs. It wakes a waiting coordinator when the
session becomes free; the existing periodic team sweep repairs a lost wake-up.
The worker rechecks the task lease, current project access, session ownership and
each referenced task and current permissions before and after reading history.
Missing or mismatched history fails closed. The selection remains attached to an already queued task if the flag is
later disabled, and a recovered task uses its own existing checkpoint.

Session metadata belongs to the source run, owner and project and is cascaded
when they are deleted. History content remains in the existing agent run records
and LangGraph checkpoints, which retain their existing lifecycle and storage
properties; this preview does not add encryption to those records, an independent
retention schedule, or a user-facing forget/export control. It passes only the
bounded selected history into each new task. Revoked members cannot read it through
the preview, and deleting a session makes a queued snapshot unavailable rather
than falling back to another person's work. Project-wide shared agent memory and
explicit lifecycle controls require separate product and privacy design.

Steering is an authorized new input to a specific running turn; audit its origin
and outcome and distinguish it from an existing checkpoint response.

## Comparison and rollout

1. Run the included synthetic cases with the same provider, model, evidence and
   instructions; save both raw results and provider usage. Add cases for each role,
   direct answers, selective delegation, dependencies, follow-ups, conflicting
   evidence, and an independent Juno review. Blind human review should score
   task completion, evidence, correct tools, delegation usefulness and failures.
   Run repeated trials, report uncertainty and total latency and cost, including
   all child turns and retries. Separate model-routing experiments from runtime
   comparisons.
2. Build an opt-in read-only adapter that uses Dotrix's real scoped tools and
   existing delegation scheduler. Compare against the full production DeepAgents
   path, including the same project context, policies and prompts. Verify session
   access isolation, cancellation, stream reconnection and steering at safe points.
3. Prove recovery by killing workers at prompt acceptance, model streaming, tool
   dispatch, tool completion, result persistence and parent resume. Include
   duplicate deliveries, expired leases, fenced workers, partial/failed dependency
   chains and SDK upgrades. Compare the authoritative effects and event history,
   not just the final text. Only then consider approved writes behind existing gates.
4. Roll out to a limited internal cohort behind an explicit flag. Keep in-flight
   runs pinned to their original runtime; disabling the flag must not strand them.
   Establish a rollback path, observability and operational ownership before any
   wider migration. Keep DeepAgents available until results justify a change.

The experiment pins `libfx` 0.0.16 (from 0.0.15 on 2026-10-30: the same journal format and engine API;
the experiment, handoff, journal, recovery, delegation, steering and continuity tests passed unchanged).
A run bound to 0.0.15 refuses to resume on 0.0.16, and 0.0.15 can't read 0.0.16's journals, so let
running fx conversations finish, then upgrade every worker together. Its [SDK documentation](https://github.com/vercel-labs/fx/tree/main/sdk)
describes sessions, host tools, durability, steering, and provider support. Recheck
the installed version's API and behavior before upgrading: the SDK is experimental
and its main-branch documentation can evolve independently of this prototype.


## Context parity and host model routing

The fx Nova preview now uses the shared `project_rules` and `build_context_pack`
builders for project maps, recent changes, layered workspace/project guidance,
accepted lessons and the skill catalog. The binding stores an encrypted context
snapshot for recovery, including the connected-code checkout context. A repository
push while waiting for specialists does not change the resumed instructions; new turns refresh it. Older bindings without a snapshot
fail closed. The total instructions must fit libfx's 64 KiB limit; oversized
instructions are refused, with no silent truncation of guidance.

The read-only tools share DeepAgents builders: document outline/sections/search,
full reads and folder/glob/grep, issues, graph relationships, connected-code reads,
and configured platform web tools. Every call checks current capability, project
visibility, requester, binding and lease before and after returning evidence. No
write, Kai handoff, approval, native provider search or arbitrary local filesystem
access is added. Configured web search may still incur its normal credits.

Project owners/admins can opt into `automatic_model_routing` in Agent models.
Architecture, reviewer and project-changing briefs select the conversation/project
model; routine briefs select the specialist model. Explicit personal/agent models
win. Selection is pinned by Dotrix's scheduler for both coordinator runtimes.
It does not infer semantic importance from untrusted text or assume a particular
provider is cheaper. Configure the two models accordingly. Each requester needs
their own provider keys; missing keys never trigger a silent model downgrade.

Dotrix uses personal BYOK, with no platform-supplied LLM or platform LLM budget.
This change adds no budget controls. Existing optional per-run limits are unchanged.
Measure cost/quality with paired saved evaluations and the supplied-price report
in `experiments/fx-chat/costs.py`. No live savings claim is made without real-model
usage and quality review.
