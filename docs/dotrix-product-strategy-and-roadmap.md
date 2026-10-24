# Dotrix product strategy and delivery roadmap

22 October 2026 · Proposed plan · Repository baseline: main at 2462587

The selected initial customer is a small software team working in existing repositories. This plan turns the [durable harness proposal](./dotrix-durable-agent-harness.md) and [hybrid execution proposal](./dotrix-hybrid-execution-architecture.md) into a product strategy, a scoped first release, and delivery milestones. Implementation has begun on the dispatch foundation described below; the complete harness and OpenCode integration remain planned.

**Selected architecture: OpenCode executes coding; DeepAgents on LangGraph powers chat, planning, and specialist knowledge workflows.** Dotrix's platform owns permissions, durable orchestration, and shared state. Both engines consume the same versioned project knowledge, filtered for the current user and task. Repository onboarding uses the proposed [Repository Knowledge skill](./dotrix-repository-knowledge-skill.md), with ongoing updates as the project changes.

**Dotrix should help a team turn a real request into a reviewed, working change while keeping the project's decisions and knowledge current.** The experience should feel like working with one capable teammate who understands the project, carries authorized work forward, and returns evidence that a human can assess.

“Best” needs a measurable meaning: teams spend less time restating context, supervising execution, checking unsupported claims, and repairing changes. Our competitive claim must be earned through better outcomes on real repositories. The combination of dependable local execution, traceable project knowledge, and efficient review is a product hypothesis to validate.

**Product experience: one conversation, multiple modes of work.** Adopt [section 2 of the durable harness design](./dotrix-durable-agent-harness.md#2-product-experience-and-principles) as the product contract. The same thread retains the discussion, plan, execution, evidence, and decisions as the user moves between these modes:

| Mode | User intent | Expected behavior |
| --- | --- | --- |
| Discuss | “How would you implement this?” | Clarify the problem, inspect authorized context, explain options, and give advice. Repository changes require a subsequent implementation instruction. |
| Plan | “Create a plan for this feature.” | Produce a proposal, acceptance criteria, task breakdown, dependencies, and open questions. Preserve a version of the plan for later authorization. |
| Build | “Implement this” or approval to execute a specific plan | Record the authorized scope and start OpenCode coding sessions and permitted checks; preserve the plan and conversation context. |
| Review | “Show me what changed.” | Present diffs, actual test results, artifacts, risks, and applicable approval requests; support requested revisions within the same thread. |

Modes can change as work evolves; the interface should support that without requiring a rigid wizard. A mode label is descriptive, while tool authority comes from the user's instruction, applicable policy, and any required approval or standing rule. The platform enforces that boundary at dispatch and tool execution. Reuse valid authorization within its scope; changed scope or sensitive actions require the applicable additional decision.

**The user primarily talks to Dotrix.** DeepAgents on LangGraph powers the primary coordinator and built-in Product, Architecture, Research, Code Review, and Documentation specialists. OpenCode provides coding execution through its adapter. Specialists are hidden by default and appear as compact, expandable activity when useful. Display meaningful actions, source references, artifacts, outcomes, errors, changes, and approval requests. Keep private hidden reasoning and unrestricted internal transcripts outside the activity surface.

Specialists return structured findings, evidence references, artifacts, risks, recommendations, and completion or partial-failure status. The parent persists and reconciles these results, resolves disagreements or surfaces them for a decision, and owns the user-facing response. Start with bounded sequential specialist work; broader parallelism follows proven recovery. The Repository Knowledge skill follows the same contract and supplies shared context to the conversation and coding task.

**The nine core principles are release requirements.**

| Principle | Commitment |
| --- | --- |
| Durability before scale | Demonstrate one recoverable OpenCode run before enabling broad parallel execution. |
| One source of truth | Dotrix owns parent/child orchestration state and permissions. OpenCode owns coding execution state exposed through its adapter. Persist their references and reconcile their states. |
| Human accountability | Identify the responsible human. Sensitive actions require explicit approval or a narrowly scoped owner-approved standing rule. |
| Visible work, private reasoning | Expose useful activity and review evidence through authorized views; preserve reasoning and conversation privacy. |
| Runtime and provider neutrality | Keep model providers and coding runtimes behind stable adapters. OpenCode and DeepAgents/LangGraph are the selected stack; additional engine support is a future decision driven by evidence. |
| Least privilege | A child's authority is bounded by its initiating user, parent task, and workspace policy; delegation cannot expand it. |
| Recover, do not blindly restart | Use persisted progress and results, stable operation IDs, and reconciliation before replaying uncertain actions. |
| Isolated execution | Give independent coding runs managed workspaces and enforced resource boundaries; preserve work during recovery. |
| Auditable outcomes | Record actor, timestamp, target, result, and relevant run, source, and authorization references for consequential actions. |

**Start with teams of roughly 2–20 people using GitHub and an established development environment.** The team size comes from the existing PRD; GitHub and the supported stacks are proposed initial constraints. The buyer is usually the technical founder or engineering lead. Daily users are developers and reviewers. Begin with bounded bug fixes, small features, and changes requested during review. These provide frequent opportunities to measure value and clear acceptance criteria.

Recruit five pilot teams, including the existing Kunemi/Kumove use case if available. Observe their current workflow before promising a schedule or improvement. Select the first operating system and supported repository templates from those pilots; exercise Windows explicitly if it is included. TypeScript and Python are sensible starting candidates given Dotrix's own stack, subject to pilot demand.

**The market already offers much of the individual feature set.** These observations are based on official documentation reviewed on 22 October 2026, rather than comparative product testing.

| Observed capability | Implication for Dotrix |
| --- | --- |
| Codex supports parallel tasks in worktrees and scheduled automations with a review queue. [OpenAI announcement](https://openai.com/index/introducing-the-codex-app/) | Worktrees and background agents are expected capabilities. Differentiate through the quality and continuity of the team's workflow. |
| Cursor cloud agents can run applications and produce screenshots, videos, and logs for review. [Cursor capabilities](https://cursor.com/docs/cloud-agent/capabilities) | Working previews and trustworthy verification evidence belong in the product experience. |
| Claude Code Remote Control exposes work that continues on the user's machine, with reconnection after interruptions. [Claude Code documentation](https://code.claude.com/docs/en/remote-control) | Local execution and remote visibility alone are insufficient differentiation. |
| Linear connects issue context to coding sessions, draft PRs, and team review. [Linear coding sessions](https://linear.app/docs/coding-sessions) | Combining a board with coding is already offered. Dotrix must demonstrate a specific advantage for its selected teams. |

The proposed advantage is a repeatable loop: better project context produces better changes; review reveals corrections; accepted corrections improve the project's knowledge; subsequent tasks require less explanation. Provenance, permission-aware sharing, and measurable task outcomes make that loop credible.

**Make one complete workflow excellent first.** A representative task is: “Fix the timezone error in scheduled deliveries, preserve the existing API contract, and show that the regression is covered.”

1. Connect the existing repository. The Repository Knowledge skill inventories a pinned revision and creates a wiki covering tools, architecture, design, functional behavior, declared requirements, non-functional requirements, dependencies, data, testing, and operations. It records coverage, sources, exclusions, and unknowns. The developer confirms the environment profile and repository access. Repository-provided setup commands pass through execution policy.
2. Establish the outcome. Dotrix gathers the issue, relevant code, approved decisions, and known constraints. It asks about material ambiguity and shows a short plan with acceptance criteria. A discussion can remain a discussion; creating executable work requires clear user intent.
3. Begin within an authorized scope. The task records the repository, base revision, selected runtime/model, permitted operations, and budget. The runner creates a dedicated worktree and branch outside the user's original working directory.
4. Follow and steer the work in the same conversation. The user can see the plan, meaningful activity, changed files, and any required decisions. Stop acknowledges the request immediately and reports confirmed termination separately.
5. Verify the result. Dotrix runs the relevant checks under the selected policy, records actual command outcomes, and captures a preview when applicable. Missing checks and failures remain visible.
6. Review and publish. The reviewer sees how each acceptance criterion relates to the diff and evidence. Publication follows the reviewed scope and approval policy. GitHub supplies the authoritative PR and merge state.
7. Preserve what was learned. Dotrix proposes relevant document or decision updates and records accepted corrections. A human closes the issue under the existing policy. Rejected approaches and unresolved questions remain distinguishable from approved facts.

Success means this same task remains intelligible after closing the UI, restarting the runner, changing reviewers, or returning a week later.

**Prioritize six capabilities around that workflow.**

| Priority and capability | Product behavior | Acceptance condition |
| --- | --- | --- |
| P0: Repository Knowledge skill and living wiki | Inventory the repository, cover every required knowledge domain, record evidence and gaps, and refresh affected knowledge when sources change. Provide relevant context to DeepAgents chat and OpenCode coding. | Every inventoried path has an inspection/exclusion status and every domain has coverage or an explicit gap. Material claims have sources and evidence states. Changed sources become stale before old claims are reused as current. |
| P0: One task workspace | Keep Discuss, Plan, Build, and Review in one conversation, with a primary coordinator and compact specialist activity. | Advice and planning cannot dispatch coding without execution intent. Reopening restores the same state, decisions, diff, and outstanding work; the parent owns the response. |
| P0: Recoverable local execution | Run through an authenticated desktop runner with managed worktrees, durable progress, and safe cancellation. | The defined interruption scenarios preserve work and recover automatically or enter an explained state requiring intervention. |
| P0: Evidence for review | Connect acceptance criteria to changed files, checks, and relevant artifacts. | Every result identifies the tested revision or tree digest, environment, command, exit code, and omitted checks; later edits invalidate affected evidence. |
| P0: Team handoff and control | Share task outcomes and review artifacts with authorized teammates while preserving private conversations. | A reviewer can assess the change without receiving unrelated private chat; permission changes apply to subsequent access and actions. |
| P1: Project learning and broader automation | Reuse approved lessons and add narrow workflows beyond the P0 knowledge refresh lifecycle. | Knowledge changes retain sources and review history; duplicate events do not create duplicate work, and unchanged conditions do not generate repeated notifications. |

The first local release needs a small amount of each P0 capability. Richer context, previews, sharing, and automation can deepen after the complete loop works.

The first two additional automation candidates are CI-failure triage and proposed release-note or decision updates after a merged PR. Triage should attach logs and a diagnosis to the relevant task; starting a repair needs the applicable instruction or standing rule. Editorial updates build on the P0 source-driven wiki refresh and propose changes requiring team judgment. Both need event deduplication, a clear owner, bounded budgets, and notifications only when there is something useful to act on.

**Project knowledge is a first-class product capability.** The Repository Knowledge skill runs a resumable discovery workflow in DeepAgents/LangGraph, backed by deterministic inventory and extraction tools. Its initial coverage includes repository structure, product and functional requirements, non-functional requirements, architecture, tools, UI/UX design, dependencies, APIs, data models, tests, deployment, operations, and available decisions. Each claim carries its source, scope, version or commit, and review state. Implemented behavior, documented intent, inferred intent, and measured outcomes remain distinct.

The product must account for every path and knowledge domain in the declared scope, while exposing inaccessible sources, unsupported formats, budget-limited work, and missing business context. It cannot guarantee that source code reveals every requirement. A coverage report makes omissions actionable. Both the chat engine and OpenCode receive a task-specific context packet from this knowledge, including relevant uncertainties and freshness information.

Updates are part of P0: observe source revisions, immediately mark affected claims stale, recompute impacted pages and relationships, and publish versioned changes through existing approval policy. Keep branch proposals separate from accepted project knowledge. See the [skill design](./dotrix-repository-knowledge-skill.md) for the coverage matrix, update rules, storage mapping, and release criteria.

Use the existing graph to retrieve relevant relationships and explain impact. Expand code indexing incrementally when observed tasks need it. A full symbol/call graph across every language is a later investment. Project knowledge stays on the platform; any local cache belongs in Dotrix-managed storage, consistent with the new architecture's repository boundary.

**Review should be the clearest part of the application.** Each delivered change includes: the requested outcome; what changed and why; the exact diff; checks performed and their outcomes; known limitations; costs; and the decisions required from the reviewer. Distinguish pre-existing failures from failures introduced by the change. Use browser evidence for interface behavior when available, and retain machine-readable check results alongside summaries.

The coding model's statement that a check passed is insufficient evidence. The runner records execution results, and CI supplies independent observations. Additional reviewer agents should be used when they improve measured quality or address a specific risk. Human acceptance, execution completion, passing checks, and merge status remain separate facts.

**Keep the everyday interface simple.** The main navigation should emphasize current work, projects, project knowledge, and an inbox of items needing attention. Within a task, use the conversation as the main surface and accessible panels for the plan, changes, checks, preview, and context. Show execution location, runner availability, budget status, and meaningful recovery actions.

Keep the human responsible for the task visible while an agent executes it. Shared review should expose selected task outcomes and artifacts through an authorized view; it must not implicitly grant access to the initiator's private conversation or unrelated runs.

The activity timeline uses the specialist contract above. Show relevant states such as queued, running, waiting for approval, recovering, blocked, cancelled, and completed, with specific next actions where needed. Keep task completion, successful execution, passed checks, and accepted publication distinct. Open-in-editor and CLI access let developers use their existing tools. When a developer edits an active worktree, suspend conflicting agent writes and invalidate affected evidence before resuming.

**Build on the existing implementation.** This mapping comes from source inspection at the baseline commit; it is not a completed runtime audit.

| Existing component | What to reuse | What the new direction requires |
| --- | --- | --- |
| [Agent models](../apps/backend/src/dotrix_backend/modules/agents/models.py) | AgentRun, approvals, structured outputs, workspace scope, usage fields | Parent/child relationships, durable steps and attempts, richer transitions, and ownership/version checks |
| [Agent checkpoints](../apps/backend/src/dotrix_backend/modules/agents/checkpoints.py) and [worker](../apps/backend/src/dotrix_backend/worker.py) | PostgreSQL/LangGraph checkpoints and the arq worker | Recovery rules spanning the full task and external side effects |
| [Agent service](../apps/backend/src/dotrix_backend/modules/agents/service.py) and [coding service](../apps/backend/src/dotrix_backend/modules/coding/service.py) | Creation, approval, dispatch, and permission checks | Atomic persistence of run changes and dispatch intent: both currently commit before dispatching |
| [Agent streams](../apps/backend/src/dotrix_backend/modules/agents/streams.py) | Existing SSE delivery interfaces | Durable ordered activity with cursor replay; current live text/activity is best effort |
| [Coding models](../apps/backend/src/dotrix_backend/modules/coding/models.py) | Coding runs, sessions, persisted coding events, Git references, usage | Link execution records to the parent run and expose runtime-neutral session metadata |
| [Coding runner](../apps/backend/src/dotrix_backend/modules/coding/runner.py) and [sandbox](../apps/backend/src/dotrix_backend/modules/coding/sandbox.py) | Git handling, artifact capture, runtime wrappers, cancellation and sandbox experience | A local provider, durable workspace/session recovery, and explicit result acceptance; coding worker jobs currently allow one attempt |
| [Desktop](../apps/desktop/src/main.ts) | Electron shell and narrow preload boundary | A runner lifecycle that can operate independently of the renderer, device registration, repository registry, and local diagnostics |
| [Web client modules](../apps/web/lib/) and [Chat](../apps/web/src/screens/Chat.tsx) | API/query modules and existing conversation/coding interfaces | One task experience and consistent data loading for the paths in the release |
| [Graph](../apps/backend/src/dotrix_backend/modules/graph/) and [lessons](../apps/backend/src/dotrix_backend/modules/lessons/) | Relationships, proposals, acceptance flows | Traceability to delivered changes, context freshness, and measurement of useful retrieval |

Keep the domain boundaries explicit:

- The existing issue records describe the work to deliver; conversations capture discussion subject to existing privacy rules.
- AgentRun becomes the canonical orchestration record, subject to the initial schema audit. Coding run/session records retain execution-specific detail and link to it.
- PostgreSQL owns orchestration state, approvals, events, and dispatch intent. Redis wakes workers. Object storage holds larger permitted artifacts.
- DeepAgents on LangGraph handles conversation, intent, planning, and specialist/knowledge workflows. The platform remains authoritative for cross-run policy and durable state.
- An execution provider determines where coding work runs. The coding adapter controls OpenCode. Model selection determines which inference provider/model each engine uses within workspace policy.
- The runner owns local process management, worktree access, and enforcement. The desktop renderer presents controls and observations.

Add abstractions where a demonstrated gap requires them. Avoid creating a competing task ledger beside the existing issue/run/session records. Migrate existing sessions with explicit compatibility and rollback behavior.

**OpenCode is the selected coding runtime for the new direction; DeepAgents/LangGraph remains the chat engine.** OpenCode's official SDK is JavaScript/TypeScript and exposes a server interface, session controls, and events. A standalone TypeScript runner with a narrow OpenCode adapter is a practical initial option, with FastAPI retaining platform orchestration. Confirm runtime versions, authentication, configuration loading, cancellation, permissions, and recovery in a bounded prototype. Read-only repository discovery tools serve the knowledge workflow; authorized code edits and project command execution go through OpenCode. [OpenCode SDK](https://opencode.ai/docs/sdk/), [OpenCode server](https://opencode.ai/docs/server/).

Evaluate Vercel durable-harness in a two-to-three-day technical investigation. The repository explicitly labels its 0.0.x API experimental; its documented execution environments also need checking against Dotrix's native local-worktree requirement. Evaluate actual recovery behavior, self-hosting, storage ownership, runtime compatibility, and licensing obligations before choosing it. Keep adoption behind the runtime adapter. The investigation should end with an adopt/wrap/defer decision and evidence, not an open-ended dependency migration. [durable-harness repository](https://github.com/vercel-labs/durable-harness), [Vercel announcement](https://vercel.com/blog/making-every-harness-durable).

**Recovery and permissions must work together.** Persist intent before side effects and reconcile uncertain outcomes before replaying them. Use a transactional outbox, stable operation IDs, expiring claims, and fencing for platform writes. A database fencing token cannot stop an old process modifying local files: the runner also needs exclusive workspace ownership, lease-loss behavior, process supervision, and enforced permission limits.

**Durability is a user-visible promise across the complete task.** A conversation can contain multiple parent runs over its lifetime. Each run records its initiating instruction, authorized scope, plan/version, child dependencies, completed results, pending decisions, coding session/workspace references, artifacts, and ordered activity. Discuss/Plan/Build/Review describe work modes; execution states separately describe whether a run is queued, active, waiting, or finished.

PostgreSQL owns the platform ledger and dispatch intent; Redis wakes workers. LangGraph checkpoints preserve the agent workflow, and the OpenCode adapter inspects coding session state. Recovery uses these together with the preserved workspace and external evidence. Checkpointing the chat alone cannot establish whether a command, publication, or remote action completed.

| Interruption or ambiguity | Required recovery behavior |
| --- | --- |
| The UI disconnects or closes | Replay persisted activity from its cursor and restore the same task, without dispatching a duplicate run. |
| The coordinator or worker crashes | Reclaim work under a new valid lease, revalidate authority and inputs, reuse applicable completed child results, and continue from persisted progress. |
| OpenCode or the local machine restarts | Inspect the recorded session, worktree, running processes, and last operation. Resume where supported or report the specific recovery decision required; preserve unfinished changes. |
| A PR/action succeeds but its result is not saved | Inspect external state using the operation identity before retrying. Record an unresolved outcome if it cannot be determined safely. |
| Approval is pending when the application restarts | Restore the pending request tied to its exact scope and candidate version. Resume only under still-valid authorization. |
| A knowledge refresh is interrupted | Resume inventory/extraction, reuse applicable results, and publish only against the expected source and knowledge versions. |

The first demonstration must include an actual interruption and recovery of one OpenCode coding run, followed by review in the original conversation. Broad specialist parallelism remains gated on this result.

For the first release, loss of authorization or a lease stops new protected work. Offline journaling is bounded, contains redacted events, and does not create new authority. The runner revalidates grants and policy after reconnecting. The UI distinguishes an offline device from a confirmed stopped process. A powered-off computer cannot execute local tasks.

Worktrees protect concurrent edits; OS/container controls provide the required security boundary. Record and enforce the supported execution profile, including filesystem, network, dependency installation, and credential access. Reject a profile the runner cannot supply. Use short-lived scoped grants, approved repositories, and credentials held outside agent-readable files. Keep artifacts private by default and apply workspace/project authorization to every read.

Local execution reduces hosted compute usage, but selected code and prompts may still be sent to the configured model provider. The user must be able to understand that data flow, configure retention and model access, and set limits. Model-provider changes require the applicable workspace policy.

**Deliver through milestones with observable exit conditions.** The milestones below are proposed; none has met its exit condition. The illustrative 12–16-week private-beta horizon assumes three experienced engineers plus part-time product/design support. Re-estimate after the first milestone; a smaller team should reduce supported platforms and postpone expansion. Reliability and integration work are included in the ranges.

| Milestone | Indicative duration | Accountable role | Deliverable and exit condition |
| --- | --- | --- | --- |
| M0: Establish the evidence and contracts | 1–2 weeks | Product lead + engineering lead | Observe pilot workflows; select supported environment; record baseline metrics and 30 representative tasks; resolve intent/authorization, specialist result, schema/privacy/provider, and knowledge evidence contracts; complete the OpenCode and durability investigation. Exit with a costed backlog and a runnable thin prototype. |
| M1: One recoverable local change | 3–5 weeks | Runner/platform engineers + product engineer | Ship the four conversation modes, minimum sourced wiki, atomic dispatch, local worktree execution, persisted activity, basic diff/check evidence, approval and Stop. Exit when Discuss/Plan respect execution intent, chat and OpenCode use compatible context, and an interrupted coding task recovers into Review in the same conversation. |
| M2: Review and context that save time | 3–4 weeks | Product engineer + platform engineer | Complete incremental knowledge refresh and gap review; add criterion-to-evidence mapping, explicit sharing, GitHub checks/PR state, approved lessons, and one supported preview flow. Exit when a source change updates affected knowledge and another authorized teammate can review the result with minimal context reconstruction. |
| M3: Prove repeated team value | 3–4 weeks | Engineering lead + product lead | Run the five-team pilot, resolve failure patterns, harden installation/update/recovery, add usage budgets and targeted diagnostics, and trial two narrow automations. Exit against the quality, reliability, adoption, and willingness-to-pay gates below. |
| M4: Expand from demonstrated demand | After M3 | Product + engineering leads | Add bounded parallel children, additional supported platforms/model configurations, deeper repository analysis, then optional cloud execution. Each addition must preserve the existing contracts and improve measured outcomes. |

M0 discovery and a narrow prototype can run concurrently. Durable state, authorization, and repository knowledge underpin local execution. Reliable evidence and recovery enable the team workflow, followed by broader parallelism/cloud. Keep an end-to-end demonstration usable through M1; infrastructure progress alone is not a product milestone.

The knowledge skill is an explicit addition to first-release scope. Its coverage manifest, evidence states, shared retrieval, and source invalidation are mandatory; advanced language-specific analysis can expand after that baseline. Re-cost the illustrative schedule in M0 instead of assuming the broader knowledge work fits without a tradeoff.

**Implementation progress, 22 October 2026.** E03 has a partial foundation, merged in #138 (`codex/durable-run-dispatch`): worker-mode agent and coding dispatch intent is stored with its triggering state change; a worker sweep republishes unaccepted intent; workers claim an operation in the transaction that starts the run; superseded generations and stopped queued runs cannot start. A terminal queue delivery that never claimed the run can receive a new delivery ID without changing the operation identity. E03 still needs leases, recovery of accepted running work, bounded failure policy, and reconciliation of coding side effects. OpenCode execution, the Repository Knowledge skill, and the unified task experience have not been implemented in this slice. This dispatch foundation alone does not meet M1's interrupted-OpenCode-run exit condition.

The follow-up, merged in #139 (`codex/coding-recovery-boundary`), classifies accepted coding jobs whose queue entry has ended or disappeared while the run still says `running` as `recovery_required`. It records the worker-local checkout path and the intended branch and commit before a push, retains uncertain work, and prevents a later turn from building on an unverified result. A lost response after a push or PR request also enters this state. This is a conservative detection boundary, not an automatic resume: a recorded path may be unavailable after host loss, and no in-product resolution action exists yet. E03/E05/E06 still need ownership leases, a durable managed workspace, external GitHub outcome inspection, an audited reconciliation decision, and then a demonstrated interrupted OpenCode run.

**The first implementation backlog should be small and reviewable.** These items describe planned work rather than changes made in this document.

| Item | Depends on | Definition of done |
| --- | --- | --- |
| E01: Architecture and migration decisions | M0 observations | Map existing records, privacy rules, authoritative state, supported OS/runtime, and legacy session behavior. Reconcile the older roadmap's desktop freeze with the new local-execution decision. |
| E02: Canonical run transitions and execution links | E01 | Add compatible parent/child/attempt relationships, explicit states/versioning, intent and authorization references, structured specialist results, and links to coding records. Keep work mode and task state distinct from run state; persist applicable results for parent recovery. |
| E03: Atomic scheduling and ownership | E02 | Store dispatch intent with state changes; add idempotent consumption, claims, renewal, bounded retries, and a recovery scanner. |
| E04: Durable activity and artifact contract | E02 | Add versioned ordered events, reconnect cursors, authorized artifact manifests, and redaction. Preserve existing coding-event history. |
| K01: Repository knowledge baseline | E01, E02, E04 | Add the versioned DeepAgents skill, read-only inventory/extractors, domain coverage report, sourced wiki drafts, and authorized context retrieval for chat and OpenCode. |
| K02: Incremental knowledge maintenance | E03, K01 | Invalidate affected claims, refresh changed sources and dependent pages, preserve human edits, and publish revision-consistent updates with missed-event reconciliation. |
| E05: Registered runner and repository boundary | E01, E03 | Authenticate/revoke devices, advertise actual capabilities, bind scoped grants to runs/repositories, and support diagnostics and lease-loss behavior. |
| E06: Managed workspaces | E05 | Create/reuse the correct worktree idempotently; record its base; prevent concurrent writers; preserve dirty work and recover partial setup. |
| E07: OpenCode adapter | E05, E06, M0 compatibility contract | Start, inspect, stream, cancel, reconcile, and collect results through the supported API with pinned compatibility. Verify actual process termination. |
| E08: Minimal unified task workspace | E02, E04, K01 | Support Discuss/Plan/Build/Review in one history; enforce execution intent before coding dispatch; use scoped versioned context; show compact specialist activity, reconnection, approvals, and the parent-owned response. |
| E09: Evidence and publication | E04, E07, E08 | Capture diff and relevant checks for the exact candidate revision; show limitations; accept/reject/revise; publish idempotently with authorization. |
| E10: Recovery gates and staged pilot | E03–E09, K01, K02 | Exercise failures across persistence, queueing, execution, cancellation, knowledge refresh and publication; document supported recovery; roll out with diagnostics and a rollback path. |

E04 and the UI can progress against a mock provider while the runner is built. E05 and E06 should expose narrow contracts so UI work does not depend on undocumented process behavior. Add tests for the important failure boundaries as implementation lands.

**Measure actual delivery, including failures and human effort.** These numbers are proposed pilot targets, not current performance or industry benchmarks. Establish the baseline during M0 and review targets before M3.

| Measure | Definition | Proposed gate |
| --- | --- | --- |
| First value | Time from repository selection to a reviewable result on a supported bounded task; report environment setup separately | Median under 30 minutes once prerequisites are available |
| Human effort | Active minutes spent clarifying context, supervising, reviewing, and repairing a comparable task | At least 30% lower median than the team's current workflow, without a quality regression |
| Accepted changes | Delivered changes accepted without major rework divided by delivered changes; define major rework before evaluation | At least 70% over a minimum of 30 evaluated results; report failure and withdrawal rates separately |
| Weekly delivered value | Human-accepted tasks meeting declared checks per active team per week | Increasing through the pilot; use as the main product measure |
| Recoverability | Defined injected failures result in preserved workspace/history and either valid continuation or an explained safe intervention | All required failure scenarios pass; separately report automatic continuation rate and recovery time |
| Context correctness | Sampled material claims supported by the cited, applicable source revision | At least 90%; track unsupported claims and stale-source incidents |
| Knowledge coverage | Accounted repository paths and required domains, with analyzed, pending, excluded, unsupported, and inaccessible counts shown separately | Every scoped path and required domain accounted for; incomplete analysis remains visibly partial |
| Knowledge freshness | Time from observed source change to invalidation and refreshed publication; also report source observation lag | No known-stale claim served as current; recovery from missed events demonstrated; latency targets agreed in M0 |
| Team retention | Pilot teams still completing real work weekly in week four | At least 3 of 5; treat this small cohort as directional |
| Economics | Model usage, hosted execution, storage and support effort per accepted task, including failed attempts | Within limits agreed with each pilot; stop scheduling before known budgets are exhausted |

Track PR merge, reopen, and revert outcomes over a defined follow-up window. A large volume of generated code, token consumption, agent messages, or created tickets is not evidence of customer value.

Use the 30-task evaluation set across bug fixes, small features, refactors, and review follow-ups. Keep a held-out subset. Use the same repository revision and comparable constraints; separate same-model workflow comparisons from comparisons of the complete product. Counterbalance task order where possible to reduce learning effects. Include unsuccessful runs in reporting and publish the sample sizes.

Useful operational events include task creation, run claim, execution start, recovery classification, evidence creation, review acceptance, and observed PR merge. Record durations, IDs, reasons, revision references, and usage; avoid copying raw source, prompts, or credentials into analytics.

**Release gates must cover behavior users depend on.** Exercise: a crash between database commit and dispatch; duplicate dispatch; worker death before and after a tool result; lost connectivity; database/Redis unavailability; a stale owner; app/runner restart; cancellation during a command; permission revocation; a dirty worktree; a branch advanced externally; and a PR created just before a response is lost.

The checks must show preserved work, no duplicate protected publication, correct authorization, accurate review evidence, and a recoverable status. An ambiguous external action can require human intervention. Test cross-workspace and private-conversation access separately. Test process termination and paths on every supported OS. Runtime/session incompatibility after an update must lead to an explicit recovery path, not silent data loss.

Product acceptance must also demonstrate: “How would you implement this?” returns advice without coding dispatch; a planning request creates a proposal; an instruction to implement an identified plan starts only its authorized work; sensitive actions apply their approval policy; valid authorization is retained across recovery; specialists cannot exceed the parent's grants; activity contains useful evidence without private reasoning; and the parent reports completed, failed, and unresolved specialist work in the same conversation. Material changes to a reviewed candidate require renewed approval where policy requires it. These are planned acceptance scenarios, not checks already performed.

During the pilot, have engineers review difficult failures weekly and turn recurring failure classes into regression cases. Maintain user-visible diagnostics and operator procedures for stuck runs. Use staged runner updates and versioned event/checkpoint schemas so deployments can coexist with active work.

**Earn adoption through the team's existing work.** Offer a guided first task from an existing issue or branch. Keep GitHub as the code/review authority and support the team's existing editor. For teams using another tracker, begin with an explicit linked issue and context import; define field ownership before attempting bidirectional synchronization. A full backlog migration should not be necessary to try Dotrix.

In the pilot, compare one ordinary task each week against the team's usual approach and ask reviewers where they still had to reconstruct context. Repeated usage and concrete willingness to pay should determine the next expansion. A proposed commercial model is a team subscription for shared knowledge, coordination, and review, with clearly separated model and optional cloud usage. Test willingness to pay before building a complicated billing system or committing to exact prices.

**Expand only when the previous stage supplies evidence.**

- Add parallel specialists after single-task recovery and review are dependable. Start with a small concurrency cap, independent scopes, per-child worktrees where appropriate, and explicit integration ownership. Measure total review effort and accepted outcomes.
- Add cloud execution when pilot demand for unattended work justifies the cost. Use the same provider, approval, event, evidence, and cancellation contracts. Migration of an active local task needs an explicit checkpoint and source/artifact policy.
- Expand supported model configurations inside the selected DeepAgents and OpenCode engines when a benchmark or customer constraint justifies it. Keep provider choice and cost visible, and measure compatibility.
- Add deeper code intelligence when current retrieval repeatedly misses dependencies. Add broader connectors when missing external context demonstrably affects task outcomes.
- Extend the same workflow into design and release work: carry a design brief, supplied mockups, and the repository's design system into visual acceptance checks; then connect approved release notes and observed deployment/incident outcomes back to the task. Prioritize these extensions from pilot workflows, with protected release actions following explicit policy.

Keep broad enterprise administration, a general IDE, a marketplace, unlimited agent fan-out, general-purpose non-software projects, and a cloud worker fleet outside the first release. The existing roadmap's broad feature backlog should be reordered around the complete software delivery workflow.

**Decisions still needed belong to named roles.** Product selects pilot repositories and supported task classes; engineering selects the first OS and runtime packaging after the spike; the engineering/product leads agree the schema migration and sharing policy; the workspace owner defines allowed execution profiles and budgets. Staffing and availability determine dates. These decisions can be resolved during M0 without delaying preparation of the first demonstrable task.

The first release demonstration should be a real change in an existing repository, interrupted deliberately, recovered with its work intact, reviewed by a teammate with clear evidence, and followed by an accepted update to project knowledge. That is the concrete outcome the initial roadmap serves.
