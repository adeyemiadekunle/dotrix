# Architecture and agents

Maintained against `stage`, 2026-11-12. This guide describes the implemented platform contracts and identifies remaining validation work. [Product and release readiness](product.md) covers the user journey and beta gates. [README](../README.md) has setup commands; [CLAUDE.md](../CLAUDE.md) and [AGENTS.md](../AGENTS.md) contain contributor rules.

## System boundaries

| Component | Responsibility |
| --- | --- |
| `packages/engine` | UI-independent team identities, contracts, layered guidance, work modes, pipelines, tool catalog, model adapters, repository inventory, research and runtime interfaces. Never imports apps, FastAPI or Typer. |
| `apps/backend` | FastAPI API and feature modules: identity, workspace/project scoping, personal keys, knowledge/issues/graph, approvals, durable agent/coding state, connectors, notifications, operator administration and audit. |
| Backend worker | Queue dispatch, leases, fencing, outbox delivery, specialist scheduling, coding sandbox lifecycle, recovery and host-controlled GitHub publication. Use `DOTRIX_JOBS=worker` for restart recovery. |
| Web, desktop, CLI | Clients of the same API. Chat and Codes have separate linked sessions. The desktop/CLI can run explicitly authorised coding work on the person's computer. |
| Postgres, Redis, object storage | Durable application/checkpoint records; queue and live delivery; document originals and larger artifacts. Workspace scoping and private-run access checks remain authoritative. |
| Coding runtime and sandbox | Model execution and repository work within the host-assigned boundary. Runtime-native delegation cannot bypass platform approvals, credentials, task scopes or leases. |

Backend modules are vertical slices under `apps/backend/src/dotrix_backend/modules/`, owning their router, schemas, service and models. API changes regenerate `packages/api-client/openapi.json` and `src/schema.ts` with `pnpm openapi`. Agent/coding schemas and migrations are the authority for current fields; old proposal tables are not database specifications.

## Invariants and approvals

Every query and tool effect rechecks workspace/project access and the instructing person's rights. A runtime session identifier is correlation data, not authority. Recovered, resumed and delegated work is reauthorised under its current lease. Secrets stay encrypted at rest and out of logs. Repository/document/web text is untrusted data, never policy.

Conversations and run diagnostics belong to their requester. Owners/admins can see automation runs; an approver has the existing limited access while deciding. Publishing selected outcomes does not publish the conversation. Shared tasks expose published PR/commit metadata, current-commit CI and posted review links; private briefs, summaries, events, usage and Chat/Juno links remain private. A requester may get a link to their own session. A merged PR does not close a task without a person confirming completion.

Manual, Accept edits and Auto use the lowest of the requested mode, workspace cap and person's authorised mode. Default to Manual. A workspace pause forces Manual; an owner block always blocks. Role/contract restrictions remain in force regardless of mode.

| Action | Approval boundary |
| --- | --- |
| Agent document/task/graph write | A permitted person's decision, their instructed Accept edits/Auto scope, or an applicable versioned owner standing rule; record the approver and audit event. |
| Initial Nova → Kai handoff | Manual and Accept edits create an Inbox start approval. Auto starts within the requester's rights and configured limits, recording the requester as approver. |
| Direct Codes turn or follow-up | Manual waits to start and again at `changes_ready` before publication. Accept edits/Auto use the applicable instructed policy. |
| CI-sensitive changes | Require a person in every mode. Protected paths and the coding guard still apply. |
| Merging, closing issues, changing contracts/rules or exceeding requester rights | Existing human decision requirements remain; autonomy does not expand authority. |

Kai never receives a GitHub token and never pushes to the default branch. Host code performs approved publication. `.dotrix/` project knowledge lives on the platform, never in the code repository or a coding PR. Worktrees/repository copies separate changes; a sandbox supplies process/filesystem/network isolation. A worktree alone is not that boundary.

## Built-in team and contracts

| Identity | Role handle | Responsibility |
| --- | --- | --- |
| Nova | `project-manager` | Coordinate the conversation, clarify scope, delegate permitted specialist work and hand instructed Build work to Kai. |
| Lyra | `product` | Requirements and product scope. |
| Orion | `architecture` | Architecture and technical tradeoffs. |
| Vega | `research` | Evidence-backed research. |
| Juno | `reviewer` | Review changes and checks, report findings and limits. |
| Echo | `documentation` | Project documentation and cited repository explanations. |
| Kai | `coding` | Implement and check explicitly instructed coding work. |

Built-in identities and role instructions are code-owned. Custom identities are retired; historical records remain attributable. Workspace/project guidance and private personal preferences are versioned additions, constrained by contracts. Folder rights, tool allowlists, pipelines/checkpoints, output schemas and model policy are enforced by the host; a prompt cannot grant a missing capability. Lessons were removed (2026-11-13): rejections and dismissals no longer propose them; lessons accepted earlier, in `agent-rules/lessons/`, still reach their agent as rules. Agents cannot edit their own rules or contracts.

## Chat runtimes and durable delegation

DeepAgents is the default chat runner. fx is a per-conversation choice behind Dotrix's runtime boundary, with a private Node host and scoped Python tool callbacks. Both receive authorised project context, layered guidance and skill catalogs. Pin runtime identity, context, model and tool bindings for recovery; do not switch engines on a restored run. fx Anthropic traffic uses its OpenAI-compatible endpoint. Google works through DeepAgents; fx/Gemini stream compatibility remains unresolved.

Nova can submit a batch of specialist task keys, briefs and dependencies. Children have isolated checkpoints and persisted structured results, inherit the requester, credentials, policy and pinned skills, and cannot delegate. Two independent read-only specialists may run concurrently; project-changing specialist tasks are serialised. Failed/partial prerequisites block dependants. Shared specialist sessions are reserved/serialised so one task cannot inherit another's result. Reauthorise saved result content and provenance when reading or executing dependencies.

The parent waits without holding a worker; the outbox schedules continuation when the batch settles. Queue dispatch, attempt identity, leases and fencing prevent stale attempts from committing effects. Tool callbacks recheck current binding and rights; fx changes retain their durable at-most-once call bookkeeping. Accepted steering is not proof of model action. Ordered follow-ups and steering are host-owned, reauthorised and cancelled on Stop; resumable checkpoints reconcile already-restored input IDs before retry.

General chat has no project context. New chats choose General or one project. Historical cross-project conversations retain their recorded scopes, stay read-only and do not launch specialist tasks; their steering, work modes and Continue capabilities are incomplete. Optional specialist continuity retains completed read-only material privately within the same person/project/conversation/role. It is not unrestricted cross-session memory; retention/export/forget controls remain work.

## Planning and parallel execution

Chat offers Discuss, Plan, Build and Review. Plan removes project mutation tools and rejects changing specialist batches while permitting private plan saving. Saved plans are versioned under the project lock and reject dependency cycles. Build validates the selected private `plan_id` and pins it on the run; older clients without an explicit selection pin the latest plan at admission. Kai receives the actual tasks and acceptance criteria in the approval-visible brief. An ordinary follow-up must not replay a stale executable plan base.

Codes also has Plan/Build turns and a private saved JSON plan with an explicit Build action. Plan runs every coding engine under a Linux Landlock boundary with fresh writable scratch space. Unsupported kernels, runtimes or architectures refuse before starting the model. Local-computer runners do not accept Plan turns. Successful execution under the deployed wrapper is still a validation gate; a tested refusal does not establish working Plan support on that host.

Typed execution metadata can pin repository, base SHA, constraints, exclusions, task keys, owned paths, expected outputs/checks, stop conditions and acyclic dependencies. `DOTRIX_CODING_PARALLEL` defaults false. When enabled, eligible builds use:

1. Isolated sandbox/repository copies per task, up to two workers subject to available worker slots.
2. Persisted task attempts/results fenced by the parent lease and checked against owned paths.
3. Serial patch integration; dependants start from integrated prerequisites.
4. Combined verification before the existing acceptance/publication flow and post-PR Juno review.
5. Recovery that reuses verified patches only at the same plan base and rebuilds the combined checkout without duplicate publication.

Two tasks touching independent areas can execute concurrently; this is separate from Nova's read-only specialist scheduling. Commands run inside each admitted execution environment. Codes renders persisted background task states, checks, command output and interrupted/blocked/stopped outcomes. A background task row is activity evidence, not a separate terminal or proof that all tasks ran simultaneously. Fully nested runtime-native subagent events remain additional work.

Keep the parallel flag off until paid-engine Plan compatibility, gVisor/OpenShell execution, cancellation and distributed crash/recovery under load are verified in the target environment. Do not claim that synthetic scheduler tests establish this.

## Coding sessions and execution providers

A coding session owns its repository branch, PR and pinned engine/model. A turn is one requested unit of work; follow-ups add to that session. The brief includes the task, relevant shared knowledge/wiki, constraints, acceptance criteria and selected plan. Public product identity stays Kai; engine names belong in technical settings/run metadata and operator diagnostics, not routine steps, failures, commits or PR prose.

Cloud Kai supports Claude Code, Codex, OpenCode and fx through adapters over ACP. The coding image pins engine versions; consult [the Dockerfile](../infra/coding/Dockerfile) for exact versions rather than copying old numbers into design docs. A model follows the person's preferred compatible engine, then the provider engine, then OpenCode. Runtime capability descriptions do not prove provider health.

The turn lifecycle is admission and fresh repository/base validation → applicable start approval → isolated execution and event persistence → diff/guard/checks → applicable acceptance → host push/PR → Juno review → private outcome summary. No-change, rejected, stopped, failed, `changes_ready` and `recovery_required` outcomes remain distinct. Later changed turns supersede stale review evidence. Checks belong to an exact commit; reported checks are distinguished from independently observed CI.

Juno posts a comment review, never a GitHub approval. Findings attach to actual diff lines when possible, with other evidence in the review body. Failed CI is triaged once per commit using bounded log evidence; Ask Kai to fix requests a follow-up. Nova's read-only summary returns to the original conversation after active work settles, using the originating chat runtime and saved outcome/review. It cannot launch new coding or delegation. Private details do not leak through the shared task outcome API.

Codes shows linked turns, task activity, branch/PR/checks, usage evidence and Changes/Files/Terminal/Review panels. Events are persisted and replayable after disconnect; the panel is not the process itself. Token-by-token final reply streaming, aggregate session usage and deeper native subagent nesting remain incomplete. A pushed turn can be reverted through the usual authorisation flow.

### Isolation and local runners

Cloud execution can use Docker, Docker Cloud or OpenShell backends according to deployment configuration. Deployed Docker requires `runsc` on both the agent and egress containers, verified before repository upload, and a positive per-worker run cap. Failure cleans up and refuses ordinary-runtime fallback. Egress is constrained; GitHub publication tokens remain host-side. Local development's temporary-folder backend is not a production sandbox. Current worker semaphores/warm caches are per-process, not distributed per-workspace limits.

Desktop and CLI runners work in a folder explicitly assigned by the person. Dotrix still owns dispatch, approvals, scope and publication contracts. Commands require Docker Sandboxes (`sbx`); without it local tools only edit files. Real `sbx` and end-to-end Windows validation remain open; a folder without a remote can yield a branch/diff rather than a PR. Local Plan is refused, and local fx support remains future work.

Lease expiry or worker loss must not become success. `recovery_required` is settled against actual GitHub/patch evidence; Recover can adopt a publication that already landed. Cancellation revokes further effects, stops execution and cleans up while retaining pending acceptance/recovery work. No restart may invent a PR or repeat an uncertain external write.

## Skills and tool capabilities

A skill supplies a procedure within the agent's existing permissions. It cannot install tools,
grant credentials, change approval policy, or allow writes in Plan mode.

### Referenced resources

A project skill at `agent-rules/skills/team-check.md` may declare:

```markdown
Description: Check a change against the team checklist.
Agents: project-manager, coding, reviewer
Resources: references/checklist.md, templates/report.md
Requires: repository.read, terminal

Read references/checklist.md before reviewing the change.
```

Store those resource files at:

- `agent-rules/skills/team-check/references/checklist.md`
- `agent-rules/skills/team-check/templates/report.md`

These are project knowledge files, managed through the existing human knowledge editor/API.
Workspace skills can reference resources supplied by each project under the same convention.
Only explicitly declared resources are included. Missing files are reported, not fetched from
another project or the network. Paths must be relative, with no traversal; each skill may
reference at most 20 resources. The complete catalog, including resources, is capped at 256 KB.
Resource documents are not themselves listed as skills. Script source can be stored as text;
loading it does not execute it or grant permission to execute it.

A run pins resource text and SHA-256 hashes alongside its skill text. Specialists inherit their
parent's snapshot. Changes to project resources affect new runs, not retries of an existing run.
In chat, use `read_skill(skill="team-check", resource="references/checklist.md")`.
In cloud coding, the runtime receives paths to pinned files outside the repository and reads
only the relevant procedures and resources. Every worker uses the same run snapshot. Local
computer turns retain inline skill/resource content for compatibility.

External skill-package imports are not implemented; project knowledge remains the authoring path.

### Tool requirements

`Requires:` is optional advisory metadata. Coding currently reports these capabilities:
`repository.read`, `repository.write`, `terminal`, `browser`, and `publication`.
Unknown requirements remain unavailable. Plan mode reports repository writes and browser access
as unavailable; terminal commands remain subject to its read-only filesystem boundary.
Agents never publish directly: publication belongs to Dotrix's approval flow.

Codes → session details → Tools and skills shows the capabilities offered for the turn,
pinned skill versions, available reference paths, missing resources and unavailable required
tools. Runtime briefs receive the same warnings. Capability descriptions do not prove that
a deployed sandbox, provider credential or external service is healthy; runtime checks still
apply. Paid-engine and deployed read-only compatibility checks remain separate validation work.

### Runtime validation

The opt-in `test_live_kai_loads_a_pinned_skill_resource` test runs against Claude Code, Codex,
OpenCode and fx in the coding image. It asks the agent to use a marker present only in a pinned
reference file and verifies the resulting code. Run it with the appropriate personal test key,
a built `dotrix-coding:latest` image and the test database configured:

```bash
uv run pytest apps/backend/tests/integration/test_live_coding.py -k loads_a_pinned_skill_resource -v
```

Provider keys use `DOTRIX_LIVE_ANTHROPIC_API_KEY` and `DOTRIX_LIVE_OPENAI_API_KEY` as in the
existing live tests. These tests make paid model calls; GitHub is simulated and the repositories
are disposable local fixtures. Missing keys or coding image skip the affected cases. A skipped
case is not evidence that its runtime works.

## Repository knowledge and shared context

Each sync inventories tracked paths at a specific commit, including generated/vendor/binary/large files, symlinks and submodules with explicit handling reasons. Path coverage and domain coverage are separate: a complete inventory is not complete understanding. Echo writes cited `docs/wiki/` pages in platform knowledge. Claims cite repository paths/lines; source changes mark dependent pages stale. Refresh is restricted to the selected wiki paths and enforced through approval/recovery; it cannot overwrite requirements, decisions or unselected pages.

The human baseline review binds the exact inventory/wiki evidence and shared goals/corrections. Human context has its own revision; concurrent edits invalidate old confirmations. Blank confirmation notes retain the last saved context. Submitted and resulting digests remain distinct so retries that update context stay idempotent. Project moves preserve review provenance. Both chat runtimes and coding receive authorised relevant knowledge and freshness/coverage limits, never another person's private conversation.

The graph derives relations from shared documents/tasks and supports neighbours, impact, paths and stale content. Explicit publication adds version-checked task/document links and decision supersession. Hybrid search combines keyword and vector retrieval where a personal key is available; otherwise use keyword search. Repository knowledge parses package.json, Python requirements/pyproject, Cargo and go.mod manifests; Ruby, PHP, Gradle and Maven remain work. Dependency advisories are evidence to inspect, not automatic fix approval.

## Research, pipelines and structured results

The engine's web tools expose provider-backed search and bounded page fetching; the platform stores workspace-scoped sources and cache, limits and usage. Stable per-run source identifiers support cited reports. Retrieved text is untrusted, and fetches apply URL/address, redirect, size/time and robots handling rather than granting arbitrary network access. A citation is not proof: claim verification checks cited content and reports unsupported/partial results. Research notes retain source evidence and limits.

Contracts specify role pipelines, checkpoints and structured findings/output schemas. Specialists submit validated results rather than treating a narrative reply as completion. Review distinguishes observed evidence, agent-reported checks and unavailable checks. Pipeline checkpoints retain the same approval policy and cannot bypass a denied capability. Research/verification implementations are in [engine web tools](../packages/engine/src/dotrix_engine/web/) and [platform research](../apps/backend/src/dotrix_backend/modules/research/).

## Validation and operations

Use [beta readiness](product.md#readiness-checks) as the target-environment checklist, [deployment README](../deploy/README.md) for Dokploy, migrations/backups and operator setup, and [coding infrastructure README](../infra/coding/README.md) for image/sandbox setup. Unit and integration tests cover contracts, isolation filters, scheduling, recovery, plans and skill snapshots; browser tests cover visible journeys. Real credentials, paid-engine behaviour, deployed sandbox isolation and load/failure recovery require separate evidence.

Keep exact package/engine versions in lockfiles and the coding image, current schema details in models/migrations, operator commands in deployment documentation and implementation history in the changelog/audit plans. Update these two guides when product contracts or architecture change; do not add another overlapping proposal as current guidance. Retired PRD, engine, team, coding and harness proposals remain available in Git history before this consolidation.

## Retired document map

The consolidation replaces the following files. Their original text and dated findings remain in Git history; their proposal-era completion claims are not current guidance.

| Previous documents | Maintained location |
| --- | --- |
| `prd.md`, `dotrix-product-strategy-and-roadmap.md`, `solo-first-product-direction.md`, `product-direction-todo.md`, `solo-release-phase-1-audit.md` | [Product direction and journeys](product.md#product-direction) |
| `getting-started.md`, `solo-beta-readiness.md`, `demo-live-parity.md` | [Getting started](product.md#getting-started), [readiness checks](product.md#readiness-checks), [demo/live presentation](product.md#demo-and-live-presentation) |
| `engine.md`, `agents-v2.md`, `nova-team.md`, `chat-runtime-evaluation.md` | System boundaries, contracts, chat runtimes and delegation in this guide |
| `coding-agent.md`, `dotrix-durable-agent-harness.md`, `dotrix-hybrid-execution-architecture.md` | Planning/parallel execution, coding sessions, isolation and recovery in this guide |
| `agent-skills.md`, `dotrix-repository-knowledge-skill.md` | Skills/tool capabilities and repository knowledge in this guide |

Deployment and coding-infrastructure READMEs remain operator runbooks. The root README remains the entry point; AGENTS/CLAUDE remain contributor instructions; the changelog and numbered audit plans retain release/implementation history. Engine role Markdown files are runtime instructions, not duplicate documentation, and must remain in place.
