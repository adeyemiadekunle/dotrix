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

The first boundary now provides a common prompt/result API, in-memory sessions,
host-defined tools and streaming events. `FxRuntime` also exposes in-process
steering and cancellation, and optional local session persistence;
`DeepAgentsRuntime` accepts a caller-configured model.
The fx host is a private Node subprocess and calls tools back in Python. These
implementations advertise no platform crash recovery or approval support and are not
selected by the backend. Production adapters must implement and validate those
contracts before the platform routes a run to them. An optional scoped tool handler
receives the runtime's session ID and, on fx, its execution ID. These are correlation
data, not verified workspace, user, run or lease authority. A production integration
must bind verified execution context and recheck authorization and fencing for every
effect.

An experimental backend adapter, `agents/runtime_tools.py`, wraps the existing
project knowledge reads in host-owned runtime tools. It checks the bound session,
workspace, project, requester, run status, lease and current agent permissions both
before and after a read. Integration tests exercise both runtimes against real project
knowledge and verify revocation and stale leases. The adapter is not selected by the
chat runner: a trusted, persisted session-to-run binding and the platform's delegation,
recovery and approval contracts are still required.

The current `delegate_tasks` implementation suspends a LangGraph tool with an
interrupt, releases the parent worker, and replays that tool to read saved results
when the children finish. An fx host tool waiting in a JavaScript process is not that
contract. Before switching Nova, prove a handoff using a durable fx engine journal
and a stable delegation call ID: commit the child batch and parent wait together,
release the worker, and resume only against the persisted batch. Evaluate the SDK's
engine handoff and ambiguous-tool behavior in a failure-injection test. Do not mark
delegation idempotent or keep a worker blocked on children merely to fit the SDK.

The local `fx_host/handoff.test.mjs` experiment exercises an explicit engine handoff
against libfx's in-memory journal. It resumes an ambiguous delegation tool with the
same execution ID and returns a saved result without creating a second batch. This
establishes a possible SDK mechanism, not a durable platform implementation: it does
not exercise Postgres transactions, a worker crash, a stale lease or the real scheduler.

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
routine task to a cheaper one. Dotrix already supports a shared specialist model
and per-agent model overrides in the existing DeepAgents path. A routing policy alone
does not enforce an allowed-model list, budgets, provider credentials or cost limits;
those remain platform responsibilities. The policy does not automatically assess
importance, and SDK/model support for reasoning effort must be checked rather than
silently assumed.

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

The existing child checkpoint is per delegated task; it does not by itself establish
a reusable specialist conversation across future tasks. A persistent specialist
session should be scoped at least to workspace, project, requesting person,
specialist and an explicit conversation or task context. Sharing a single project
session would risk exposing one person's private conversation to another. Define
retention, deletion, access revocation, configuration-version changes, context
compaction, and how stale project evidence is refreshed before enabling reuse.
An ephemeral task remains useful when continuity is unnecessary or inappropriate.
Treat steering as an authorized new input to a specific running turn, audit its
origin and outcome, and distinguish it from the existing checkpoint response.

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

The experiment pins `libfx` 0.0.15. Its [SDK documentation](https://github.com/vercel-labs/fx/tree/main/sdk)
describes sessions, host tools, durability, steering, and provider support. Recheck
the installed version's API and behavior before upgrading: the SDK is experimental
and its main-branch documentation can evolve independently of this prototype.
