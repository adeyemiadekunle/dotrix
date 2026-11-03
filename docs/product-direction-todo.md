# Product direction todo

Accepted direction: 2026-11-02. This is the implementation checklist for the agreed product walkthrough. The priority index remains in [CLAUDE.md](../CLAUDE.md#remaining-work-by-priority-2026-10-30); this document holds the journey details and acceptance criteria. Production and permission requirements in that index still take precedence.

Dotrix helps a solo developer or an organisation turn an idea or an existing GitHub codebase into planned, reviewed work. The product loop is:

**Idea or repository → project understanding → agreed scope → saved knowledge and tasks → Nova–Kai handoff → implementation → Juno review → human merge → project update.**

## Decisions to preserve

- One person has one account and can use a personal workspace and belong to multiple organisation workspaces. A Dotrix workspace and a GitHub account/organisation are separate concepts.
- A project is the home for work. An early idea can be a lightweight draft project with a working title; it does not need a repository, dates or a completed specification.
- GitHub and model setup are required only when the chosen activity needs them. Project management remains available without a model key. GitHub sign-in does not grant repository access.
- Agent runs use the instructing person's connected model credentials. Preserve personal BYOK and existing authorised model routing; do not add platform LLM budgets or borrow a colleague's credentials.
- Nova coordinates the fixed specialists selectively. Kai implements explicitly instructed coding work. Chat and Codes have separate sessions with visible links to the originating task, outcome and review.
- Dotrix owns permissions, approvals, durable delegation, recovery and audit. Runtime/framework details do not become ordinary onboarding decisions. Preserve one level of specialist delegation.
- Conversations remain private. Sharing an outcome means an explicit, permission-checked publication into project knowledge or tasks; it must not expose the surrounding private conversation.
- Project knowledge remains on the platform; `.dotrix/` never enters a coding PR. Juno reports evidence and limitations. People retain the merge decision.

## Existing foundation — reuse, do not rebuild

- [x] Personal and organisation workspaces, membership roles, invitations, restricted projects and personal-to-organisation conversion exist.
- [x] Project tasks, Board/List, Knowledge, project activity and the fixed built-in team exist.
- [x] DeepAgents and fx chat use Dotrix's specialist scheduler; model policy, permissions and approvals remain host-owned.
- [x] Separate Chat/Codes sessions, Nova–Kai handoff, coding panes, PR outcomes and Juno reviews exist.
- [x] Connected-repository inventory, explanation, coverage and stale-knowledge indicators exist.
- [x] First-project onboarding, optional GitHub/personal-model setup, retained navigation without a key, and shared demo/live presentation are implemented in [PR #214](https://github.com/adeyemiadekunle/dotrix/pull/214).
- [x] Merge the onboarding foundation: PR #214 merged into stage on 2026-11-02.
- [ ] Verify the onboarding foundation in the target environment. A merge is not evidence of deployment.

## Delivery order

### J01 — Unify onboarding and later project creation

- [x] Use one project-setup flow for the first project and subsequent projects, with shared validation and server-confirmed saves.
- [x] Default solo signup to the existing personal workspace; create a team workspace only when explicitly requested.
- [x] Give invited members a join-first route into the intended workspace/project, preserving invitation and return destinations. Do not require them to create an unrelated project.
- [x] Preserve setup across refresh, authentication and GitHub installation redirects. Resume an existing saved project instead of recreating it; make retry behaviour explicit after uncertain requests.
- [x] Keep GitHub and model setup deferrable for project-management-only work. Never put provider keys in URLs or browser storage.

Implementation: shared `/onboarding` setup for signup and live New project actions; current workspace/mode and confirmed project IDs survive return paths; failed saves refresh saved work before another attempt. Invitation signup joins first, and local return destinations survive password, GitHub and email-link authentication. Team/project save recovery requires explicit selection of saved work. GitHub and model setup remain optional. See `onboarding.spec.ts`, `auth.spec.ts` and `test_magic_link.py` for the regression scenarios. Deployment verification remains separate.

Done when: a solo signup, a team founder, an invited member and an existing user adding another project each reach the correct saved workspace/project without duplicates or unnecessary setup.

### J02 — Offer three starting intentions

- [x] Present **Explore an idea**, **Start a new codebase**, and **Connect an existing repository** in the shared setup flow.
- [x] Explore an idea saves a lightweight project with a working title and opens a useful Nova discussion after model setup when needed.
- [x] New-codebase setup collects the goal before asking for repository details. Existing-repository setup asks for GitHub access and repository selection.
- [x] Let a documents-only or idea project connect a repository later without losing its tasks, knowledge or conversation links.
- [x] Ask Nova to clarify goals, users, constraints and uncertainties before proposing scope; delegate only where specialist input is useful.

Implementation: three explicit choices in shared setup, retained through the project's existing source field and recovered from saved state. Ideas skip GitHub and can start with only a working title; new codebases require a saved goal before repository setup. Ready actions open editable Discuss starters without launching a run. Project Overview offers repository setup on the existing project; the connector regression checks preservation of tasks, knowledge and the conversation. See `project-start.spec.ts`, `onboarding.spec.ts` and `test_connectors.py`. Deployment verification remains separate.

Done when: each intention leads to a suitable first action, and an idea can become an implementation project without starting over.

### J03 — Complete new repository to first reviewed implementation

- [x] Expose the existing organisation-repository creation capability in the shared flow, subject to the person's current rights and GitHub installation permissions.
- [x] Confirm repository owner, name and visibility before creation. Handle cancellation, name conflicts, revoked access and uncertain responses without silently creating duplicates.
- [x] Provide a clear personal-GitHub path: create the repository on GitHub, grant the App access, refresh and connect it. Do not imply that the current App integration can create personal-account repositories. Evaluate another authorised creation mechanism only as a separate decision.
- [x] Verify fresh/empty repository initialisation and a valid base branch before a coding session starts; show an actionable prerequisite when it cannot start.
- [x] Carry an approved initial task and its project knowledge through Nova → Kai → checks → PR → Juno → Nova, with the person performing the merge.

Repository-setup slice: shared onboarding exposes organisation creation with an explicit owner/name/visibility review and cancellation before submission. Created repositories still require explicit attachment. An unconfirmed response refreshes available repositories and blocks automatic creation retries; an existing name is selected rather than silently adopted. Personal accounts receive the GitHub-create → README → App access → refresh/select path. The API rechecks the current installation owner and suspension before creation. See `repository-create.spec.ts` and `test_connectors.py`. There is no durable creation-attempt journal; refresh recovers from GitHub’s repository list and owner/name uniqueness, not from a saved Dotrix attempt. Readiness and first-PR implementation: the scoped read-only readiness endpoint checks the live installation, current repository/default branch and a committed head using a repository-scoped read token. New cloud/local sessions, assignments and Nova handoffs check it again before creating a coding run; a waiting run keeps its validated base, and a later fetch failure stops before model execution. Shared setup shows actionable empty/unavailable states and an editable Plan starter, with no automatic model call. The first-PR regression covers personal GitHub/personal workspaces and organisation GitHub/team workspaces on DeepAgents and real libfx, from a README-only repository through saved knowledge, plan, Manual start/publication approvals, recorded checks, a PR, scheduled Juno review and a single private Nova outcome. The outcome inherits the original chat runtime; fx admits that host-created Review turn read-only, without write/coding/delegation tools. The PR stays open and main stays unchanged for the person’s merge decision. See `repository-readiness.spec.ts` and the first-PR cases in `test_coding.py`. GitHub/model traffic is synthetic; no production deployment or paid-provider quality result is implied.

Done when: a solo developer using personal GitHub and a team using a GitHub organisation can each reach a first reviewed PR through a supported, clearly explained path.

### J04 — Establish a baseline for existing repositories

- [x] Guide a connected project through inventory, repository explanation and a review of the resulting baseline.
- [x] Show the inspected commit, coverage, exclusions, unsupported files and unresolved questions. Repository access must not imply complete understanding.
- [x] Invite the person to add goals, requirements and existing documents that code cannot establish; distinguish these from inferred implementation facts.
- [x] Let the person confirm or correct the baseline before using it to propose substantial changes.
- [x] Surface stale knowledge after repository changes and offer a scoped refresh that preserves human-authored decisions and requirements.

Implementation: existing-project onboarding and Overview lead to Knowledge → Coverage. The existing inventory, per-domain gaps, exclusions, unsupported paths, cited wiki pages and stale-source indicators remain visible; pages can be opened for review. A shared human review records goals/corrections separately from inferred wiki facts and binds confirmation to a server digest of repository identity, known commit/checkouts, coverage, wiki revisions and the project knowledge revision. Missing inventory/citations or stale sources block confirmation, and partial coverage requires an explicit acknowledgement. A lost-response retry reuses its request ID; changed evidence requires a new acknowledgement and stale submissions fail. Shared human context has a separate revision in the evidence digest; another editor’s correction invalidates an older open review. A fresh blank confirmation preserves that context, and the submitted digest is kept separately for safe retries after a context update. Reviews are shared project records, never private transcript publication or approval to implement. Shared context tells both chat runtimes whether a baseline is confirmed and quotes human notes as evidence; regular Chat/Code remain available for independently instructed work. The reviewed-baseline action opens an editable Plan draft and makes no model call.

Refresh can select individual stale pages; the selected write paths persist on the run and survive approval/recovery. The storage boundary confines discovery to docs/wiki/ and confines a selected refresh to those exact pages, preserving requirements, decisions and unselected pages even if the model requests an approved write elsewhere. Reviews follow a moved project and become out of date when its evidence or human documents change. Tests: `test_repo_knowledge.py`, `repository-baseline.spec.ts`, existing Coverage/project-start scenarios. GitHub/model metadata in tests is synthetic; deployment and real-model explanation quality remain separately unverified.

Done when: an existing project reaches a useful, evidence-backed summary and next-step proposal, with its uncertainties and freshness visible.

### J05 — Turn private discussion into shared project work

- [x] Offer explicit actions to save selected outcomes as requirements, decisions, research or tasks, using the existing knowledge and issue services.
- [x] Preview the selected content, destination and project visibility before applying the existing permission and approval rules.
- [x] Preserve permitted provenance and links among the saved artifact, task, coding session, review and PR. Never give teammates access to a private transcript through a source link.
- [x] Support correction and superseding decisions without silently replacing human-authored knowledge or losing version history.
- [x] Return implementation and review outcomes to the originating conversation and keep shared task status accurate, distinguishing an open PR from merged work.

Shared coding evidence implemented: teammates see published PR/commit evidence, current-commit CI and already-posted review links on the task, without private coding/Chat access. Open, merged, closed without merging and unconfirmed states remain distinct; only a person closes the task. Existing Nova/Juno private outcome delivery is retained. Combined integration tests follow published scope through the shared task to PR/review evidence while denying private conversation access.

Done when: a teammate can understand agreed scope, its rationale and its implementation outcome from shared project records without reading another person's chat.

Publication foundation implemented: completed private project replies expose an edited selection and explicit visibility preview for new requirements/decisions/research documents or unassigned tasks. Existing permissions, atomic retry records and create-only documents prevent duplicate retries and silent replacement. Owners retain private destination links after reconnect; shared records have no automatic transcript links. Later human edits keep Knowledge versions. Shared relationships now include reviewed, version-pinned document/task references and explicit decision supersession, with atomic new-version annotation of the predecessor and graph navigation in Knowledge. Shared task evidence connects those records to published PR/commit/check/review metadata without exposing private coding or Chat sessions. Deployment verification and paid-model quality remain separate.

### J06 — Bring in an existing GitHub backlog

- [x] Start with an explicit, previewed import of GitHub Issues into the selected project, mapping supported states, labels, assignees and source links.
- [x] Define the authoritative system for each imported field and explain what is imported once versus kept in sync. Begin with a bounded import rather than implying full two-way synchronisation.
- [x] Deduplicate by repository and source issue identity; handle repeat imports, partial failures and revoked access without duplicate tasks or cross-project leakage.
- [x] Keep unknown users, unsupported fields and mapping conflicts visible for review.
- [x] Treat GitHub Projects boards, ongoing synchronisation and other trackers as follow-on scope, with separate migration and conflict rules.

Done when: a team imports a representative existing backlog, verifies the mapping and retries safely without rebuilding its tasks manually.

Implementation: project Board/List import entry opens a bounded, selectable preview with field mappings, provenance and warnings. Confirmation rechecks the current source and permissions and commits all selected new tasks atomically. Stable source records skip existing/imported/deleted work; saved preview selections make lost-response retries safe. Dotrix owns fields after this one-time import. Live GitHub verification remains separate from synthetic transport tests.

### J07 — Explain project readiness and the next useful action

- [x] Show project readiness from saved state: purpose captured, relevant knowledge available, repository connected when needed, baseline freshness, and implementation prerequisites.
- [x] Show personal model readiness to the current person only; distinguish stored credentials from a verified successful model call.
- [x] Recommend the next useful action for the current intention: clarify the idea, explain the repository, review scope, create a task, connect prerequisites or implement an approved task.
- [x] Explain permission restrictions and unavailable integrations without blocking unrelated work or presenting simulated success.
- [x] Apply the same readiness rules and presentation to onboarding, project pages and empty states; keep demo content explicitly illustrative.

Done when: a new or returning person can tell what is ready, what is missing and how to proceed without guessing from an empty screen.

Implementation: a shared saved-state readiness API and panel serve onboarding, Overview and empty task views. Readiness distinguishes real repository bindings from URLs, baseline revision freshness, meaningful knowledge from untouched templates, personal key availability from current-key successful-run evidence, and implementation preparation from live execution admission. Viewing guidance never invokes a provider or changes project state; actions open existing setup, manual work or editable Nova drafts. Live journey verification remains separate.

## Verification and release checklist

- [ ] Solo idea → draft project → useful proposal → saved scope/tasks → later repository connection.
- [ ] Solo personal GitHub → supported repository creation/connection path → first task → reviewed PR.
- [ ] Team founder → organisation workspace → GitHub organisation → project → invited member participation.
- [ ] Invited member → correct project; board/task work without a model key; agent work with their own authorised credentials.
- [ ] Existing repository → inventory/explanation → reviewed baseline → imported backlog → next approved change.
- [ ] Refresh, expired authentication, GitHub redirect, save failure, interrupted request, provider limit and retry preserve confirmed state and do not duplicate work.
- [ ] Changed roles or repository permissions are rechecked before resumed actions; private conversations, keys and restricted project content remain scoped.
- [ ] Both chat runtimes preserve the same project journey, permissions and Nova–Kai handoff. Verify UI flows with deterministic models; any paid-provider checks are separately identified.
- [ ] Record evidence per delivered item, distinguish merged code from deployed behaviour, and update this checklist and CLAUDE.md together.

## Simplify and defer

Do not add arbitrary agent creation, recursive specialist teams or mandatory runtime selection to deliver these journeys. Do not force GitHub on idea exploration, or model setup on people only managing tasks. Keep the current Chat/Codes separation and fixed identities.

Defer a large standalone Ideas system, portfolio features, cross-organisation joint ownership, enterprise SSO/custom roles/billing, broad tracker migration and additional code hosts until the core journeys are dependable. These remain roadmap items, not deleted requirements. A lightweight draft-project journey and explicit outcome publication come first.

## First implementation slice

J01 implements shared project setup, correct invited-member handling, and server-confirmed project saves. Verify the onboarding foundation in the target environment separately. J02 now supplies the three starting intentions. J03 now implements the new-repository-to-reviewed-PR journey with regression coverage; target-environment verification remains separate. J04 now implements the reviewed existing-repository baseline. J05 implements explicit publication of private discussion outcomes into shared project work, and J06 adds reviewed one-time GitHub Issues imports. J07 now provides consistent saved project readiness and next actions; live journey verification and release readiness remain. Reuse current workspace, GitHub, model, project and conversation services. Do not replace the agent runtime to implement this product direction.
