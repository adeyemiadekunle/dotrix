# Repository Knowledge skill and living project wiki

22 October 2026 · Proposed product design · Repository baseline: main at 2462587

This design extends the [product strategy and roadmap](./dotrix-product-strategy-and-roadmap.md) for small software teams with existing repositories. Initial discovery and ongoing maintenance are P0 capabilities. This document specifies planned behavior; the skill and supporting infrastructure have not been implemented or validated.

## Product purpose and runtime ownership

On connecting a repository, Dotrix should build useful project knowledge, show the evidence and gaps, and keep that knowledge aligned with subsequent changes. Developers should be able to ask how something works, understand the intended constraints, and start a coding task without repeatedly explaining the project.

| Component | Responsibility |
| --- | --- |
| DeepAgents on LangGraph | Chat, planning, the Repository Knowledge skill, synthesis, and specialist workflows |
| OpenCode | Authorized code edits, builds, tests, and other project command execution |
| Dotrix platform | Access policy, durable run state, source revisions, approvals, publication, retrieval, and update scheduling |

The proposed built-in skill is `repository-knowledge`, with bootstrap, refresh, and coverage-review modes. Its versioned procedure uses structured, read-only inventory and extraction tools. Running repository scripts requires the authorized coding execution path. Repository content is input to analysis and cannot grant additional tool authority.

The skill follows the [conversation and specialist principles](./dotrix-durable-agent-harness.md#2-product-experience-and-principles): the user talks to the Dotrix coordinator, and repository analysis appears as compact activity when useful. The skill returns structured findings, coverage/gaps, evidence references, draft artifacts, risks, and completion status for the parent to reconcile. Discuss and Plan can inspect permitted context; coding starts with clear implementation intent and the applicable authorization. Knowledge publication separately follows the existing write/approval policy.

Discovery and refresh use the durable parent/child run contract: record the pinned inputs, coverage progress, completed results, pending approvals, and ordered activity. Following an interruption, reuse results valid for those inputs, reconcile pending publication, and continue from persisted progress. Reopening the conversation restores its activity and decisions. The skill inherits the parent's authority and budget limits; running it does not expand access.

Devin's DeepWiki provides a useful reference: its documentation describes generated repository explanations, diagrams, and source links, and offers configuration to guide coverage when important areas are missing. Dotrix should pair this readable experience with explicit coverage, requirement provenance, and context shared by both engines. These are proposed Dotrix capabilities, not assertions about Devin's internals. [Devin DeepWiki documentation](https://docs.devin.ai/work-with-devin/deepwiki).

## Three connected outputs

1. **Living wiki:** navigable explanations of the product, implementation, design, development workflow, and operations, with source links and visible uncertainty.
2. **Coverage and evidence index:** structured records connecting files, modules, requirements, decisions, and wiki claims to their sources and freshness. Extend the existing project graph where required.
3. **Task context packet:** a bounded selection of relevant knowledge for DeepAgents chat or an OpenCode task, including applicable constraints, commands, sources, and unresolved questions.

The wiki is a view over canonical project knowledge. It must not become an independent store that diverges from requirements, architecture documents, and decisions. Generated context packets are disposable projections of versioned knowledge.

## Required coverage

The initial inventory includes every tracked path at the selected revision. The following domains must each have evidence, a documented exclusion, or an explicit gap.

| Domain | What the skill records |
| --- | --- |
| Product and domain | Purpose, supported users, domain vocabulary, capabilities, business context, and boundaries; distinguish documented intent from inference |
| Functional requirements | User journeys, roles, permissions, business rules, state transitions, inputs, outputs, validation, errors, edge cases, and integrations; separate observed behavior from approved requirements |
| Non-functional requirements | Declared performance targets, availability, reliability, scalability, security, privacy, accessibility, compatibility, maintainability, and recovery expectations; identify supporting implementation and validation evidence separately |
| Architecture | Entrypoints, packages, services, responsibilities, module relationships, request and event flows, background jobs, queues, boundaries, and architectural decisions |
| Design and UX | Screens, routes, navigation, component patterns, design tokens, typography, assets, interaction states, responsive behavior, accessibility conventions, and linked design specifications |
| Tools and development | Languages, runtimes, frameworks, package managers, environment-variable names and purposes, setup, build, lint, formatting, code generation, and test commands with their working directories |
| Dependencies | Internal package relationships, direct external dependencies, versions and constraints, lockfile-resolved transitive dependencies where supported, external services, and evidenced licensing information |
| APIs and contracts | Routes, schemas, events, authentication, authorization, callers, error handling, versioning, and documented compatibility promises |
| Data | Entities, relationships, schemas, migrations, persistence boundaries, declared retention and deletion behavior, and data movement |
| Quality | Test suites, fixtures, CI checks, relevant requirement-to-test links, known gaps, and the revision of any imported execution results |
| Delivery and operations | CI/CD, deployment environments, infrastructure definitions, observability, release procedures, runbooks, backups, recovery procedures, and documented support ownership |
| Decisions and history | Available ADRs, accepted decisions, approved lessons, linked issues/PRs, known debt, and unresolved contradictions; historical search is bounded and its limits are disclosed |

Inventory lockfiles with deterministic parsers where supported; summarize their implications for humans instead of sending every transitive dependency to a model. Dependency presence does not establish usage, vulnerability status, or legal compliance. Additional analysis needs its own evidence and scope.

External design files, private specifications, production configuration, and unwritten business rules may be absent from the repository. Record a missing-source gap and request the smallest useful clarification. Do not infer that an absent requirement does not exist.

## Coverage is accountable, not an absolute completeness claim

“Without missing anything” should mean **no silently skipped part of the declared scope**. Source code alone cannot establish all business intent, operational targets, or desired behavior.

Each inventoried path has a status: analyzed, pending, excluded, unsupported, or inaccessible. Exclusions include their reason and policy version. Generated code, vendored dependencies, binaries, submodules, and large assets remain visible in the inventory even when their contents are excluded or require separate access. Discovering a submodule does not mean its contents were inspected.

Report path coverage, domain coverage, and evidence quality separately. A file being read is not proof that its meaning was fully understood. A source citation is not proof that a claim correctly follows from it. Budget limits leave visible pending work and a resumable cursor, rather than a misleading completion label.

Show an initial overview while deeper analysis continues. Use separate inventory-complete and discovery-complete statuses: discovering every path does not mean analyzing every source. Discovery remains partial while in-scope work is pending, unsupported, or inaccessible. A finished pass can still contain unknown requirements or missing external evidence; those gaps and any explicit scope exclusions remain visible alongside its status. Every mandatory domain needs a coverage result and a list of unresolved material questions.

## Discovery and publication workflow

1. **Pin the scope.** Record workspace, project, repositories, default branch and commit, accessible external sources, exclusion policy, skill version, analysis limits, and initiating instruction or standing rule. Multiple repositories retain separate revision identities.
2. **Inventory deterministically.** Enumerate paths; identify languages, workspaces, manifests, lockfiles, routes, schemas, tests, CI, infrastructure, design assets, and existing documentation. Persist coverage before synthesis begins.
3. **Extract and map.** Use supported parsers and structured readers to build module and dependency relationships. Record parser limitations. Capture commands as documented/configured facts without executing repository scripts during discovery.
4. **Explain each domain.** DeepAgents follows the skill to synthesize sourced pages, connect requirements to implementation, identify design conventions, and list gaps. Checkpoints make large repositories resumable.
5. **Reconcile contradictions.** Preserve discrepancies between documentation, implementation, tests, and approved decisions. “Implemented this way” and “required to work this way” are separate claims. Route consequential disagreements to the appropriate owner.
6. **Review coverage and evidence.** Check source references, unresolved links, required domains, orphan modules, exclusions, and pending work. Spot-check material semantic claims; mechanical checks cannot establish all of their correctness.
7. **Publish through existing policy.** Propose versioned changes through the authorized specialist and knowledge service. A scoped owner standing rule can authorize routine updates; other changes wait for the applicable approval. Persist retrieval and graph updates consistently with the accepted knowledge version.

Team corrections become reviewed knowledge changes with attribution. An agent cannot silently overwrite them merely because a later generation produces different wording.

## Evidence and freshness contract

Each material claim needs a stable identity, domain, scope, source references, generation/run reference, and independent evidence, review, and freshness states. Prefer named states to an unexplained numeric confidence score.

| Dimension | Examples |
| --- | --- |
| Basis | Observed in code/configuration; declared in an approved requirement; inferred from available evidence; unknown |
| Validation | Static inspection; test definition located; test result observed; runtime measurement observed; unverified |
| Review | Draft; approved; disputed; superseded |
| Freshness | Current for a named source snapshot; stale; refresh pending; source unavailable |

A repository source includes repository identity, commit SHA, path, applicable line range or symbol, and content hash. External sources include their version or retrieval timestamp and access scope. Record dependent source relationships so changes can invalidate derived claims.

For example, “the API has a 300 ms latency target” needs a requirement source. Finding a benchmark file only establishes that the benchmark exists. Claiming the target was achieved requires an actual result, workload, environment, and tested revision. Finding an authorization check does not establish a general security guarantee.

## Maintenance as the project grows

Observe changes to the accepted repository branch, approved decisions, knowledge documents, and connected sources. Also support manual refresh. Source observation and freshness bookkeeping are platform operations; generated content publication follows the existing approval policy.

- Deduplicate and coalesce events by workspace, repository, target revision, and skill version. Persist work and retry from checkpoints.
- When a source change is observed, mark dependent claims stale before they can be served as current. If impact is unknown, invalidate the broader affected domain.
- Compare snapshots, inspect changed and added files, retire deleted sources, and refresh dependent pages and relationships. A lockfile, shared schema, root configuration, or architectural change can require a broader pass.
- Reconcile the complete path inventory on each new repository snapshot. Graph relationships alone cannot discover a newly added module that has no prior edges.
- Publish against the expected prior knowledge version and target source generation. An older run finishing late must not replace a newer baseline. Reuse unchanged claims only where their source and dependency applicability remains established.
- Preserve human edits with version checks and reviewable diffs. Present conflicts and behavioral changes explicitly; keep reviewed intent when implementation drifts.
- Reconcile the current source head periodically to recover missed webhooks. Record the last observed revision/time. If observation fails, expose freshness uncertainty rather than claiming to know the latest source state.
- Handle rewritten history, permission changes, and large structural changes with reconciliation or a broader rebuild as required.

Branch proposals and uncommitted work use task-scoped overlays. They cannot redefine accepted project behavior before the corresponding source or decision is accepted. Successful coding execution alone is insufficient evidence that the shared baseline changed.

After a PR merges, show “what knowledge changed and why” with the source diff and proposed page changes. A person should only need to act on meaningful gaps, disagreements, or updates requiring review.

## Context shared by chat and coding

Both engines request knowledge through the same authorized retrieval contract. Each packet includes the task's repository/base revision, compatible knowledge versions, relevant requirements and acceptance criteria, architecture and design constraints, affected dependencies, documented commands, source links, and material stale or unknown items.

DeepAgents uses it to answer questions and plan work. OpenCode receives the relevant packet when coding begins and can request further context. The whole wiki need not fit into every prompt. Retrieval can expand from a concise summary to full cited sections and source files.

If the task's branch differs from the wiki baseline, compare relevant sources or create an overlay before applying the knowledge. A hard requirement must not disappear simply because a relevance search ranks it poorly: include applicable approved constraints explicitly. Missing critical context should cause targeted clarification or inspection.

Code changes can propose new knowledge, but source reconciliation and authorized publication determine what becomes canonical. Both engines must be able to explain which version and sources informed their work.

## Fit with the current repository

Reuse the existing foundations instead of introducing another knowledge ledger:

| Existing code | Proposed extension |
| --- | --- |
| [Skill definitions](../packages/engine/src/dotrix_engine/skills.py) and [skill loading tools](../apps/backend/src/dotrix_backend/modules/agents/knowledge_tools.py) | Add a built-in procedure and version tracking; preserve workspace defaults and project overrides |
| [DeepAgents construction](../packages/engine/src/dotrix_engine/agent.py) and [checkpoints](../apps/backend/src/dotrix_backend/modules/agents/checkpoints.py) | Run discovery and refresh as resumable specialist workflows |
| [Knowledge models](../apps/backend/src/dotrix_backend/modules/knowledge/models.py) and [service](../apps/backend/src/dotrix_backend/modules/knowledge/service.py) | Reuse versioned content, attribution, conflict checks, and publication; add source/claim/coverage metadata |
| [Project graph models](../apps/backend/src/dotrix_backend/modules/graph/models.py) | Extend document/issue/module relationships with source dependencies and claim provenance; file/symbol coverage is new work |
| [Context assembly](../apps/backend/src/dotrix_backend/modules/agents/context.py) and [knowledge index](../packages/engine/src/dotrix_engine/knowledge_index.py) | Add revision compatibility, mandatory constraints, freshness checks, and a shared packet contract for OpenCode |
| [Code service](../apps/backend/src/dotrix_backend/modules/code/service.py) | Reuse permitted repository reading; add snapshot inventory and supported extractors |

Keep platform-managed knowledge outside the user's code repository, consistent with the hybrid architecture. Local caches belong in managed Dotrix storage. Scope reads, sources, derived summaries, and retrieval by workspace/project and source access; revocation must affect subsequent access to derived content too. Do not place private chat or secrets into shared wiki pages.

Existing [folder permissions](../packages/engine/src/dotrix_engine/permissions.py) remain authoritative: Documentation owns `docs/*`, Product owns `requirements/*`, and Architecture owns `architecture/*`. Documentation may tidy other permitted areas without changing their meaning. The skill coordinates drafts through those owners; it does not acquire blanket write rights. Owners/admins control `agent-rules/*`; agents cannot rewrite their own procedure or authority. These paths refer to platform knowledge namespaces, not a new directory to push into the code repository.

## User experience and release criteria

The project Knowledge view should provide domain navigation, source-linked pages, coverage/gaps, a recent-changes feed, and reviewable proposed updates. Each page shows its source revision, freshness, and review state. Users can correct a claim, supply a missing source, or request deeper analysis without editing an agent prompt.

Before release, demonstrate the following on supported pilot repositories. These are proposed acceptance scenarios, not completed tests:

1. An unfamiliar repository produces coverage across every required domain, with no silently omitted paths or inaccessible modules.
2. Missing business rules, design specifications, and non-functional targets remain explicit gaps; observed behavior is never promoted to approved intent automatically.
3. A newly added module, renamed/deleted source, and dependency update each affect the appropriate inventory, pages, and context.
4. Duplicate events, interruption, a lost webhook, and out-of-order completion preserve a consistent baseline without duplicate publication.
5. Human corrections survive refresh; conflicting edits and documentation/code disagreements appear for review.
6. Private sources and revoked access do not leak through summaries, context packets, or stale cached results.
7. Chat and OpenCode receive compatible context for the same task; an unmerged branch cannot contaminate the accepted baseline.
8. Repeating a run against unchanged inputs does not create unnecessary page versions or notifications. Report analysis time, cost, pending work, and sampled claim correctness.

Implement K01 (inventory, coverage, sourced drafts, and shared retrieval) and K02 (invalidation, incremental refresh, conflict handling, and reconciliation) from the roadmap. Start with the pilot languages and repositories while exposing unsupported coverage. Deeper symbol analysis and additional connectors can follow. Re-estimate delivery with this P0 scope included.
