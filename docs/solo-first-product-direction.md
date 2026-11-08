# Solo-first product direction

## Goal

Make Dotrix a dependable workspace where a solo developer can turn an idea or an existing GitHub repository into a planned, implemented and reviewed change. Release a focused private beta when that journey is useful and trustworthy; learn from real users before widening the scope. Team collaboration is a later product phase, while the existing workspace and permission foundation is preserved.

The core journey is **idea or repository → understand → agree on a task → approve Kai → implement and check → review → human decides what happens next**.

This document is a direction and release plan, not evidence that a feature is complete or deployed. Audit the current implementation and test it in the target environment before making completion claims. Continue to apply the security, privacy, approvals and workspace-scoping rules in [CLAUDE.md](../CLAUDE.md) and [AGENTS.md](../AGENTS.md).

## First user and starting paths

The first user is a solo developer building or maintaining software. Dotrix should support three starting intentions:

1. **Explore an idea:** clarify what to build and save useful decisions.
2. **Start a new project:** turn a goal into initial scope and tasks, then connect code when ready.
3. **Connect an existing repository:** understand the codebase, choose a task and make a reviewed change.

Project management remains useful without a model key. Require GitHub and model setup only for actions that need them; GitHub sign-in and repository access are separate.

## Onboarding

Use a focused, step-by-step flow: one main decision per screen, concise explanations, visible progress and a clear way to skip optional setup. The proposed sequence is:

1. **Welcome:** confirm or edit the person's name; create or select a personal workspace without requiring organisation setup.
2. **Choose a starting point:** offer the three paths above.
3. **Name the project:** save a working title and, when useful, a short goal. A draft need not have a repository or completed specification.
4. **Connect GitHub:** explain what access enables, select a repository where relevant, and allow the person to skip when the chosen work permits it.
5. **Connect an AI provider:** explain personal provider keys and allow setup later; make readiness and any missing prerequisite clear when an AI action is requested.
6. **Begin:** show what is ready and offer a useful first action in the project, chat or task flow.

Resume safely after refresh, authentication or GitHub redirects without duplicate projects. Do not lead solo onboarding with teammate invitations, organisation setup, optional profile details or marketing subscriptions. Do not offer a region choice unless the deployment actually supports it. Adopt the clarity and pacing observed in Linear's onboarding while retaining Dotrix's own identity and product-specific choices.

## Product experience

### Navigation and project work

Make Home, Projects, Chat, Codes, Tasks and Settings understandable to one person. Home should surface what needs attention and the next useful action. Keep project documents and tasks lightweight: show the instructions and evidence needed for the work, distinguish an open PR from reviewed and merged work, and remove unnecessary friction. Review visible fields and views against the solo journey before deciding what to retain.

### Nova and specialists

Conversations are personal. Nova should distinguish general questions from work in a specific project, read only the context needed, identify and delegate to the fixed specialists by their product names, and distinguish directly read evidence from assumptions or task descriptions. Active work, Stop, steering and queued follow-ups should be clear; acceptance of steering is not proof the model acted on it. Explain failures and limitations plainly. Publishing selected chat outcomes into shared project knowledge or tasks is explicit and previewed; do not expose the surrounding private conversation.

### Kai and review

Nova prepares a structured, permission-checked handoff containing the goal, scope, constraints and acceptance criteria. The person can inspect the approval request before Kai starts. Codes links to the source chat and task, shows progress and Stop, and reports changed files, checks and limitations. Juno's review and the PR should be visible with the coding outcome and returned to the original chat when available. The person retains the merge decision. Dotrix owns authorization, approvals, isolation, audit, recovery and model policy; runtimes must not bypass those controls.

## Release scope

**Essential:** personal account and workspace; three starting paths; projects and later repository connection; documented supported GitHub and model-provider configurations; Nova chat and authorized specialist delegation; simple tasks and knowledge; an approved Nova → Kai → Juno journey; PR, check and review evidence; Stop and truthful failure/recovery states; personal provider-key management and understandable usage; and a secure deployment with a sandbox verified in the target environment.

**Simplify or hide:** team invitations and member dashboards; workload and manager reports; advanced fields and settings that do not serve the initial journey; duplicate actions and unnecessary explanatory labels; and features that lack a reliable user journey.

**Defer:** full team onboarding and collaboration, organisation administration and enterprise controls, broad integration expansion, additional agents and complex automations, and unverified features presented as production-ready.

Do not delete team support, existing data, workspace isolation or authorization merely because team-facing work is deferred. Review usage, dependencies and migration impact before retiring a feature. Personal BYOK remains the model policy; provider usage and infrastructure have separate costs.

## Findings to investigate

Recent local live testing identified the following; confirm each against the current version before implementing a fix:

- Nova did not consistently recognize Lyra by name even though specialist activity used that name.
- The delegated product specialist reported `code_read` unavailable while Nova could read the connected repository. Investigate authorized tool access without weakening permissions or leases.
- A fresh Nova → Kai → Juno run must demonstrate that the PR and review return to the originating chat. A task displayed a review that a separate conversation could not verify; examine provenance and scope before changing access.
- Finish and verify the composer Stop/Send, queue and steering interaction. A submitted steering message alone does not prove delivery or model action.
- Surface available model and usage evidence; measure routing and quality before claiming savings.
- Report unavailable tests or dependencies honestly and verify the production sandbox independently of local Docker.
- Exercise each onboarding path and recovery after redirects or interruption without duplicate saves.

## Delivery phases

### 1. Audit and decide

Inventory the current screens and capabilities. Assign each **keep**, **revamp**, **hide/defer** or **remove**, with a reason, dependencies, migration impact and required work. Do not infer removal merely from a feature being outside the first release.

### 2. Fix the core loop

Resolve confirmed identity, specialist access, composer and coding-outcome issues. Verify handoff constraints, approval decisions and truthful results. Done when a developer can take a scoped repository task through an unmerged, reviewed PR and receive evidence and limitations in the original chat.

### 3. Simplify onboarding and navigation

Audit and adapt the existing implementation. Exercise all three starting paths, optional setup and resumption after interruption. Done when each path reaches a useful first action without requiring team setup or creating duplicates.

### 4. Prepare a private solo beta

Verify deployment, account recovery, provider and GitHub setup, sandbox isolation, failure handling and support paths in the intended environment. Document the supported configuration and known limitations.

### 5. Learn and iterate

Invite a small group of solo developers. Observe completion of real tasks, abandonment points, recovery needs, costs and return usage. Use evidence to revise, defer or remove features before a wider release.

## Release criteria

- A new person can create a personal project and return to it.
- Supported GitHub and provider setup works, can be deferred where appropriate, and reports failures.
- Nova and specialists are identified correctly and use only authorized context.
- A scoped task completes the approved coding and review loop, with the originating conversation linked.
- The person can inspect changes, checks, review and limitations, including checks not run.
- Stop, failures and recovery states are accurate; no success or review is invented.
- Provider usage and infrastructure limitations are understandable.
- Sandbox isolation and recovery are verified in the deployment environment.
- The interface has been reviewed for unnecessary team-oriented complexity.

## Team phase

After the solo loop is reliable, use observed needs to plan organisation onboarding, invitations, roles, shared project context, collaboration and reporting. Preserve existing privacy and permission boundaries. Begin with the feature audit, not an assumption that all existing team features should be removed.
