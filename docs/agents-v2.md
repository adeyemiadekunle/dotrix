# Agents v2: spec

Status: reviewed 2026-09-29; D1, D2, and D6 decided (§12). Plan: "Plan: agents v2" in [CLAUDE.md](../CLAUDE.md).
Background: the 2026-09-29 review of our agents against ChatGPT's workspace agents, dots, and
Space (DevDay 2026), deep-research agents, code knowledge graphs, and AGENTS.md / Agent Skills.

## 0. Step 0: one tenant, Personal or Organisation

Decided (D6); built 2026-09-29 (the endpoint is `POST /v1/workspaces/{id}/convert-to-organization`,
project people are at `.../projects/{id}/members`). Before it, an organisation (`modules/organizations`) was a layer of roles above several
workspaces, and the workspace is the tenant: `workspace_id` on 12 tables and every query, the
isolation suite, and `/w/{slug}` URLs. The two overlap. The workspace stays the tenant and
takes on the organisation's job; the organisations layer goes.

- **Kinds:** `personal` (one per person, just its owner, never invites) and `organization` (a
  team: invites, roles, many projects). `team` and `business` go.
- **Roles:** the workspace roles (owner, admin, member, guest) are the organisation's roles. Org
  owners' implicit access through `MembershipRepository.effective` goes; access is a membership.
- **Migration (dev and test data only):** team and business workspaces become organisations;
  an org owner who could see a workspace through the organisation gets an owner membership
  there; org admins and members keep only the memberships they had. Drop `organizations`,
  `org_memberships`, and `workspaces.organization_id`; drop the org routes and the `{org_id}`
  scope from the isolation suite.
- **Invites** need `kind == organization` (was: the workspace belongs to an organisation). A
  personal workspace never invites.
- **Turn into an organisation** replaces attach: a personal workspace becomes an organisation
  with its projects, and its owner gets a new, empty personal workspace. Moving a project
  between workspaces stays as built (#56, #57).
- **Project access** replaces "several workspaces per team": `Project.access` is `workspace`
  (every member) or `restricted` (owners and admins, plus the people in `project_members`).
  `require_project_permission` checks it, so a restricted project is a 404 to anyone else;
  project lists, search, the calendar feed, and the approvals queue filter by it; the
  isolation suite gets a restricted project in its `World`.
- **Web:** the switcher lists Personal and your organisations; "Create organisation" makes an
  organisation workspace; the `/o/…` pages go, their people and settings move into the
  organisation's settings; project settings gain "Who can see this project".
- **Agents v2 scope (D2):** contracts, skills, the Space, and automations belong to the
  workspace (Personal or Organisation), with per-project overrides where the spec says so.
- **Delivery:** (1) backend model, migration, removals, invites, "turn into an organisation";
  (2) project access; (3) web. **Acceptance:** the backend, CLI, and browser suites pass with
  organisations removed; a restricted project is invisible to a member not added to it; a
  personal workspace turned into an organisation keeps its projects and can invite.

## 1. Goals and non-goals

**Goals**

- Owners and admins change what an agent is (instructions, tools, folder access, model,
  budget, how much it may do alone) and create new agents for a specific purpose. The six
  built-in agents stay, as editable defaults with "Reset to default".
- Every agent works through a declared pipeline and returns a declared result, so the app can
  show its progress and offer actions on each result ("Create issue", "Fix now", "Dismiss").
- Research reads and cites its sources, and checks its own claims.
- Agents understand how the project's pieces relate (a knowledge graph), and later the code.
- Agents work in the background on events and schedules, and tell people what they found.
- A shared space per workspace, above projects.

**Non-goals (for v2)**

- Our own coding agent. Coding goes to Claude Code or Codex (Phase 5).
- A graph database. Postgres tables and recursive queries are enough at our size.
- Real-time co-editing of documents.
- Agents acting without a person being accountable. Every run, background ones included, is
  instructed by a person and audited.

## 2. Where we start

| Piece | Today | File |
|---|---|---|
| Who the agents are | The PM plus five specialists, prompts and tools hard-coded | `packages/engine/src/pmagent_engine/agent.py` (`build_team`, `_subagents`, `LEADS`) |
| What they may write | A fixed folder matrix and issue-type rules | `packages/engine/src/pmagent_engine/permissions.py`, enforced in `KnowledgeService.write` |
| Customising | Text only: `agent-rules/base.md` + `<role>.md`, prepended to the prompt | `_with_rules`, `AgentRunner._rules` |
| Approvals | Every write (`write_file`, `edit_file`, gated board tools) interrupts; approve / edit / reject | `interrupt_on` in `build_team`; `AgentService.decide` |
| Who leads a chat | `AgentRun.agent`: null (Auto) or a role | `agents/schemas.py` (`AgentChoice`) |
| Research | The provider's native search tool only (snippets); nothing stored about sources | `_web_search_tool`, `agents/llm.py` |
| Context | The context pack (index, board, decisions, what changed) and hybrid search | `agents/context.py`, `modules/search` |
| When agents run | Only when a person chats, asks for a briefing, or drafts the architecture | `agents/service.py` |

The spec keeps everything that works: the approval gate and audit, attribution per agent
(`lc_agent_name` → role), the context pack, budgets and usage breakdown, the checkpointer,
the run queue and streams.

## 3. Principles

1. **Contracts are data, invariants are code.** A contract can narrow or widen what an agent
   does within limits the code enforces. No contract can switch off an invariant (§4.4).
2. **Built-ins come from code until someone edits them.** A workspace that never customises
   anything behaves exactly as today, and code changes to the defaults reach everyone who
   hasn't overridden them.
3. **The engine stays UI-agnostic.** Contract schemas, the tool catalogue, pipelines, output
   schemas, and the search provider interface live in `packages/engine`. Storage, APIs,
   triggers, and the UI live in the platform.
4. **A person is always accountable.** A run is instructed by a person (chat) or by the person
   who owns an automation (background). Standing rules that let an agent act without asking
   are themselves approved, versioned, and audited.
5. **Text from documents, repos, and the web is data, never instructions**, including the
   repo's own `AGENTS.md` / `CLAUDE.md`.

## 4. Step 1: agent contracts

### 4.1 The contract

A contract is a Pydantic model in the engine (`pmagent_engine.contracts.AgentSpec`),
validated on every save and on every run.

```yaml
handle: security            # [a-z][a-z0-9-]{1,30}; unique in its scope; `@security` in chat
name: Security reviewer
description: Reviews changes for security risks.   # one line, shown in the + menu
base: reviewer              # built-in it was cloned from, or null (from scratch)
instructions: |             # Markdown; replaces the built-in role prompt
  ...
model: null                 # null: the conversation's model (lead) or the specialist model
budget_tokens: 150000       # null: the project's budget, else the server's
tools:                      # ids from the catalogue (§4.3)
  - knowledge.read
  - knowledge.search
  - board.read
  - issues.create
access:                     # folder patterns (relative to .pmagent/) -> read | propose | write
  reviews/*: write
  requirements/*: read
issue_types: [bug]          # types it may create (when it has issues.create)
can_call: [architecture, research]   # agents it may hand work to (one level deep)
skills: [triage-bug]        # step 2
autonomy:                   # per action id (§4.5); anything unlisted: ask
  issues.comment: allow
  issues.close: block
output: finding             # result schema (§4.6); null: free text
pipeline: reviewer.issue    # declared stages (§5); null: free-form
triggers: []                # step 4; stored now, inert until then
```

### 4.2 Storage and resolution

- `agent_definitions`: `id`, `workspace_id`, `project_id` (null: the workspace's), `handle`,
  `base` (a built-in role or null), `current_version`, `archived_at`, `created_by_id`,
  timestamps. Unique `(workspace_id, project_id, handle)`.
- `agent_definition_versions`: `definition_id`, `version`, `spec` (JSONB), `note`,
  `author_user_id`, `created_at`. Append-only, like knowledge versions.
- **Resolution for a project:** project override → workspace definition → built-in default
  (from code). The result is a list of `AgentSpec` plus, for each, where it came from
  (`built_in`, `customised`, `custom`).
- **Built-ins are rows only once edited.** Editing a built-in creates a definition with
  `base = <role>`. "Reset to default" archives it. Nothing is seeded per workspace.
- Every save writes a new version and an audit event (`agent.created`, `agent.updated`,
  `agent.archived`, `agent.restored`) with the diff of the spec.
- Runs record the handle and the version they ran with (`AgentRun.agent`,
  `AgentRun.agent_version`), so a run's behaviour can be explained later.

### 4.3 The tool catalogue

`pmagent_engine.catalog` lists every tool an agent can be given: id, description, risk class,
and the actions it can take. The platform supplies the implementations (as today with
`build_board_tools` and `build_knowledge_tools`).

| Id | Tools | Actions (for autonomy) |
|---|---|---|
| `knowledge.read` | `ls`, `read_file`, `glob`, `grep`, `document_outline`, `read_section` | none |
| `knowledge.search` | `search_knowledge` | none |
| `knowledge.write` | `write_file`, `edit_file` (still limited by `access`) | `knowledge.write` |
| `board.read` | `list_issues`, `get_issue` | none |
| `issues.create` | `create_issue` (limited by `issue_types`) | `issues.create` |
| `issues.update` | `update_issue` | `issues.update`, `issues.close` |
| `issues.comment` | `comment_issue` | `issues.comment` |
| `issues.label` | `label_issue`, `link_issue` (new, low risk) | `issues.label` |
| `web.search` | `web_search` (§6) | none |
| `web.fetch` | `fetch_page`, `fetch_pdf` (§6) | none |
| `graph.read` | `graph_neighbors`, `graph_impact`, `graph_path` (§8) | none |
| `graph.propose` | `propose_edge` | `graph.write` |
| `code.read` | `code_search`, `read_code`, `blast_radius` (§10) | none |
| `delegate` | `task` to the agents in `can_call` | none |

The file tools are always present in deepagents, so "not given" for the file tools means
filtered by the existing `CompactTools` middleware plus `access`: an agent without
`knowledge.write` has every write denied, as the reviewer is today.

### 4.4 Invariants (in code, whatever a contract says)

1. Agents never write `agent-rules/`, contracts, automations, or skills. People change those.
2. An agent never exceeds the person it acts for: a run's writes are also checked against the
   instructing person's permissions (a member's request still waits for an owner or admin).
3. `access` can grant `write` on any folder except `agent-rules/*`. It can't make a folder
   writable that the project matrix marks people-only.
4. `issues.close` needs a person: an agent may propose closing, never close alone (as today,
   only a person moves an issue to `done`).
5. Guests never see project content; agents never read another workspace's data.
6. `.pmagent/` never goes into a code repo; coding hand-offs carry code only.
7. Every tool call that changes something is audited with the agent, its version, who
   instructed the run, and who approved it, or which standing rule allowed it.
8. Text read from documents, repos, and the web is data. Contracts can't change that line of
   the base rules.

### 4.5 Autonomy: allow, ask, block

- Every action (the "Actions" column above) is `ask` unless the contract says otherwise.
- `block`: the tool isn't given for that action, and the service refuses it anyway.
- `allow`: the action runs without interrupting. It is only offered for **low-risk actions**:
  `issues.comment`, `issues.label`, `graph.write`. Document writes, creating and updating
  issues stay `ask` in v2.
- **Decided (D1):** a standing `allow` rule is a pre-approval by an owner. CLAUDE.md's rule now
  reads: every agent write is approved, by a person at the time or by a standing rule an owner
  approved (low-risk actions only; versioned and audited). Only owners set `allow` rules.
- In the approval queue, a low-risk action gets "Always allow this for <agent>", which saves a
  new contract version (owners only; admins can set `ask` and `block`).
- The audit event of an allowed action records `approved_by = null` and
  `details.rule = {definition_id, version}`.

Implementation: `build_team` builds `interrupt_on` from the contract (every `ask` action's
tools), drops `block` tools, and passes `allow` tools through ungated.

### 4.6 Output contracts

- An agent with `output` set ends its run by calling `submit_result(items=[...])`. The tool's
  schema is the output schema, so any provider returns valid structured data. A plain-text
  reply is still written for the conversation.
- Stored in `agent_run_outputs`: `run_id`, `schema`, `items` (JSONB), and per item a `state`
  (`open`, `done`, `dismissed`) with who acted and the link to what it produced (an issue key,
  a knowledge version, a hand-off).
- Schemas (engine, `pmagent_engine.outputs`):

| Schema | Item fields | Actions in the app |
|---|---|---|
| `plan` | step, agent, expected output, estimate | Approve plan, edit, stop |
| `spec` | document path, sections, stories (title, acceptance criteria) | Review proposed batch |
| `impact` | affected ref (requirement, ADR, module, issue), why, severity | Open, create task |
| `finding` | severity, title, detail, refs (files, modules, issues), suggested fix, fingerprint | Create issue, Fix now (Phase 5), Dismiss with reason |
| `report` | claim, source ids, confidence, affects | Propose change, create spike, record decision |
| `doc_update` | path, reason, related change | Review proposed edit |
| `brief` | issue, acceptance criteria, excerpts, tests to run | Send to Claude Code / Codex |

Findings are deduplicated by `fingerprint` against open findings and issues in the project.

### 4.7 Pipelines and checkpoints

- A pipeline is a named list of stages in the engine (`pmagent_engine.pipelines`). The
  agent's prompt lists them; it reports each with `stage("name")`, streamed as a `stage`
  activity event and used to split the run's token breakdown by stage.
- A **checkpoint** is a stage marked `steer`. The agent calls `checkpoint(summary, plan)`,
  which interrupts with kind `steer` (not an approval of a write). The person who asked (or an
  owner or admin) can continue, edit the plan, or stop. Members can steer their own runs.
- Checkpoints are skipped under a size threshold (the plan estimates a small job) and in
  background runs, where the automation's settings decide.

### 4.8 API

All under `/v1/workspaces/{workspace_id}`, owners and admins to change (`MANAGE_WORKSPACE`),
everyone who sees projects to read.

| Route | What |
|---|---|
| `GET /agents?project_id=` | Resolved agents, with `source` and version |
| `GET /agents/catalog` | Tools, actions, output schemas, pipelines (for the editor) |
| `GET /agents/{handle}` | One agent's current spec |
| `PUT /agents/{handle}` | Create or update (new version); body: spec + note; 409 on a stale `base_version` |
| `DELETE /agents/{handle}` | Archive a custom agent, or reset a built-in |
| `GET /agents/{handle}/versions`, `POST /agents/{handle}/versions/{v}/restore` | History and restore |
| Project overrides | The same under `/projects/{project_id}/agents/...` |

- Runs: `agent` accepts any resolved handle (the `AgentChoice` enum becomes a validated
  string). `auto` stays the PM.
- `tests/integration/test_isolation.py`: add `handle` to `World.params` and a body for `PUT`.
- `pnpm openapi` after each change.

### 4.9 Engine changes

- `build_team(..., agents: list[AgentSpec], lead: str | None)` builds the PM and subagents
  from specs. `_subagents` goes; the current prompts become the built-in specs in
  `pmagent_engine.builtins`, so defaults are unchanged.
- `role_for_agent_name` maps `<handle>-agent` to the handle; `permissions.access(agent, path)`
  takes the spec's `access` first, then the built-in matrix.
- `can_create_issue` / `can_edit_issues` read `issue_types` and the tools.
- Local mode (`build_agent`) keeps using the built-in specs.

### 4.10 Web and CLI

- **Settings → Agents** (workspace settings; project settings for overrides): the list with
  badges (Built-in, Customised, Custom); an editor with sections: identity, instructions
  (Markdown), model and budget, tools (checkboxes from the catalogue), folder access (a table
  with read / propose / write), issue types, agents it may call, autonomy (allow / ask / block
  per action, invariants disabled with a reason), output and pipeline; history with diffs and
  restore; "Try in chat".
- **Chat:** the + menu and `@handle` list every resolved agent.
- **CLI:** `pmagent agents list`; `pmagent chat --agent <handle>` accepts custom handles.

### 4.11 Evals

- **Structural evals in CI** (scripted model, `pmagent_engine.testing`): per built-in and per
  pipeline, saved cases in `packages/engine/tests/evals/<agent>/*.yaml` check that the stages
  run in order, only granted tools are called, blocked actions are refused, writes interrupt,
  and the output validates against its schema.
- **Quality evals, on demand** (`pmagent eval --live --agent research`, needs a model key; not
  in CI): the same cases scored against expected facts. Prompt changes to built-ins come with a
  run of these.

### 4.12 Delivery (PRs) and acceptance

1. Engine: `AgentSpec`, catalogue, built-in specs, `build_team` from specs. **Acceptance:** all
   existing tests pass unchanged; a spec-built team behaves as today.
2. Platform: tables, resolution, API, audit, runs by handle, isolation rows. **Acceptance:**
   create, edit, reset, restore; a custom agent leads a chat; attribution and folder checks
   use its spec.
3. Web: Settings → Agents, chat menu. CLI: `agents list`, `--agent <handle>`. Browser test:
   create an agent and chat with it.
4. Autonomy (after D1) and "Always allow this" in the approval queue.
5. Output contracts, stages, checkpoints; the findings list with actions.
6. Structural evals in CI.

## 5. Step 1b: the pipelines

Each is the default for its built-in agent; custom agents pick one or none. Built 2026-10-01 in
`pmagent_engine.pipelines` (stages with guidance, `steer` checkpoints, run modes for triage and
issue review); stages that need the graph (step 3), web tools (1c), or code (step 5) say so and
fall back to search and documents until those land.

| Pipeline | Stages (`steer` marks a checkpoint) | Output |
|---|---|---|
| `pm.request` | classify (question / change / plan / triage) → answer from context, or plan (`steer` when large) → dispatch (parallel where independent) → merge → one batch of proposed writes → follow-ups (`current-state.md`, roadmap) | `plan` then free text |
| `pm.triage` | read the report → duplicates (search + graph) → classify type, priority, area → propose issue with links, or comment on the existing one | `finding` / proposed issue |
| `product.spec` | clarify (ask when ambiguous) → related requirements, issues, ADRs → spec from the template → consistency check → proposed document + epic and stories as one batch | `spec` |
| `architecture.impact` | the change → impact (project graph; code graph when connected) → options and trade-offs → recommendation → ADR draft (to Documentation), module map update, tasks | `impact` |
| `research.report` | plan (`steer` when large) → our knowledge and earlier research first → web search → read pages → extract claims with quotes → verify → report → save to `research/` | `report` |
| `reviewer.coverage` | requirements → board → code (when connected) → done / partial / missing per requirement | `finding` |
| `reviewer.issue` | the issue in `review` → acceptance criteria → the coding agent's notes and PR → close or send back with changes | `finding` |
| `reviewer.commit` | diff → blast radius → related requirements and issues → findings (step 5) | `finding` |
| `docs.update` | the approved change → affected documents (graph neighbours) → proposed updates; ADRs from decisions; staleness sweep on a schedule | `doc_update` |
| `coding.brief` | issue → acceptance criteria → linked excerpts → blast radius → tests to run → hand-off (Phase 5) | `brief` |

## 6. Step 1c: research

### 6.1 Tools

- **Search provider interface** in the engine (`pmagent_engine.search.SearchProvider`:
  `search(query, *, recency_days, include_domains, exclude_domains, limit)`), with Tavily,
  Exa, and Brave implementations and a `FakeSearch` for tests. Settings:
  `PMAGENT_SEARCH_PROVIDER`, `PMAGENT_SEARCH_API_KEY`. Without a key, the model's native
  search stays as the fallback (today's behaviour). **(you)** choose the provider (D3).
- **`fetch_page(url)` / `fetch_pdf(url)`** return Markdown (via `ingest.to_markdown`) with a
  source id. Safety: http(s) only; public addresses only (no private, loopback, or link-local
  IPs, checked after DNS resolution and on every redirect); 2 MB and 20 s limits; allowed
  content types; robots.txt respected; per-domain rate limit. Fetched text is wrapped as
  untrusted data before the model sees it.
- A cache per workspace (`web_pages`: URL hash, fetched at, content hash, Markdown), reused for
  a day, so repeated research doesn't refetch. Per workspace, so nothing crosses workspaces.

### 6.2 Sources and claims

- `research_sources`: `id`, `workspace_id`, `project_id`, `run_id`, `url`, `title`,
  `publisher`, `fetched_at`, `content_hash`, `tier` (`primary`, `reputable`, `other`).
- Each claim in a `report` item cites source ids and a **quote**. Verification has two parts:
  a deterministic check that the quote occurs in the stored page (normalised whitespace,
  fuzzy match above a threshold), then a model check that the quote supports the claim.
  Result: `supported`, `weak`, or `unsupported`. Unsupported claims are moved to
  "Assumptions" in the saved report.
- The saved `research/*.md` note has the fixed sections (question, short answer, findings,
  assumptions, open questions, what it affects) and a sources list with dates.
- Pages that contain instructions aimed at the agent are flagged in the report.

### 6.3 Watches (needs step 4)

A watch is an automation (§9) with the research agent and a topic: it re-runs the pipeline on
a schedule, compares claims with the last report, and creates an inbox item only when
something changed, with proposed document updates to approve.

### 6.4 Acceptance

- With `FakeSearch`, a research run plans, searches, fetches, verifies, and saves a report with
  sources; a quote that isn't in the page is marked unsupported.
- The SSRF checks are unit-tested (private IPs, redirects to private IPs, non-http schemes).

## 7. Step 2: rules that layer and learn

- **Layers, most general first:** base rules (code) → workspace contract instructions →
  project `agent-rules/base.md` and `agent-rules/<handle>.md` → the agent's lessons. The more
  specific layer wins where they conflict (the prompt says so). Organisation rules (FR-17)
  join as the first layer once organisations have a knowledge store (after step 6). The
  invariants (§4.4) are appended last and can't be overridden.
- **Skills:** a skill is a versioned Markdown procedure with a name and a one-line
  description, stored per workspace (same versioning as contracts) or per project
  (`agent-rules/skills/<name>.md`). A contract lists its skills; the agent sees their names
  and descriptions and loads one with `load_skill(name)` when needed. Built-in skills: write
  an ADR, triage a bug, write a spec, scope a failing build, write a research note.
- **Lessons:** after a rejection with a reason, a dismissed finding with a reason, or a person
  editing an agent's proposed write, a small job (specialist model, budgeted) proposes one line
  for `agent-rules/lessons/<handle>.md`. It appears in the approval queue as "Proposed lesson";
  approved lessons join the agent's prompt; they're versioned and can be removed like any file.
- **Repo conventions:** once a repo is connected (step 5), its `AGENTS.md` / `CLAUDE.md` are
  read into coding briefs and commit reviews as quoted data (how to build and test,
  conventions), never as instructions to our agents.
- **Templates:** `agent-rules/templates/<folder>.md` (requirements, ADR, research note, design
  brief), used by the pipelines' "from the template" stages.

## 8. Step 3: project knowledge graph

### 8.1 Model

- `graph_nodes`: `id`, `workspace_id`, `project_id`, `kind`, `ref`, `title`, `version`,
  `updated_at`. Kinds and refs:

| Kind | Ref | From |
|---|---|---|
| `issue` | `KUN-12` | issues |
| `doc` | `requirements/checkout.md` | knowledge files |
| `section` | `requirements/checkout.md#payment` | headings (`knowledge_index.sections`) |
| `decision` | `decisions/ADR-004.md` | ADRs |
| `module` | `module:payments` | `architecture/modules.md` (maintained by the architecture agent) |
| `finding` | `research/…#S3`, `run:<id>/<n>` | research and review outputs |
| `person`, `agent` | user id, handle | memberships, contracts |
| later `commit`, `pr`, `file`, `symbol` | sha, number, path, path:symbol | step 5 |

- `graph_edges`: `id`, `workspace_id`, `project_id`, `src_id`, `dst_id`, `kind`
  (`implements`, `depends_on`, `decided_by`, `affects`, `supersedes`, `mentions`, `owned_by`,
  `blocks`, `parent_of`), `origin` (`derived`, `parsed`, `agent`, `person`), `evidence`,
  `created_by`, `created_at`. Unique `(src_id, dst_id, kind)`.

### 8.2 Keeping it current

- **Derived** (exact): issue parent, dependencies, links; ADR supersedes lines.
- **Parsed** (deterministic): issue keys mentioned in documents and descriptions (`mentions`),
  `Affected modules:` in ADRs (`affects`), module paths in `architecture/modules.md`.
- **Suggested by agents** (`propose_edge`, action `graph.write`): e.g. "KUN-12 implements
  requirements/checkout.md#payment". Low risk, so `allow` is possible once D1 is agreed.
- Sync runs like `KnowledgeIndex.sync`: on write for the changed item, and before a graph read
  under the project's advisory lock, so reads are always current.

### 8.3 Queries and uses

- Tools: `graph_neighbors(ref, depth ≤ 2, kinds?)`, `graph_impact(ref)` (everything that
  depends on or implements it, transitively, capped), `graph_path(a, b)`. Recursive CTEs with
  depth and row limits.
- API: `GET .../projects/{id}/graph?ref=&depth=` for the Knowledge tab's graph view.
- **Context pack:** "Related to this request": the neighbours of refs named in the message
  (issue keys, paths, module names), instead of relying on the whole index.
- **Staleness:** a section is stale when a node it `affects` or `implements` changed after the
  section did; briefings and the documentation sweep list them.
- **Acceptance:** on the dev project, "what does changing checkout.md#payment affect?" returns
  the stories, ADRs, and modules linked to it; graph reads are under 100 ms at 5,000 issues.

## 9. Step 4: triggers, background runs, inbox

- **Automations:** `automations` (`id`, `workspace_id`, `project_id`, `agent_handle`,
  `trigger` JSONB, `message` template, `owner_user_id`, `enabled`, `daily_token_budget`,
  `last_run_at`). Created by owners and admins; the owner is the run's "instructed by".
- **Triggers:** `schedule` (cron, the worker's scheduler), `issue.created`, `issue.changed`
  (filters: type, status, labels), `document.changed` (path pattern), `approval.decided`,
  `run.finished`, and in step 5 `commit.pushed`, `pr.opened`, `ci.failed`.
- **Events:** an `events` outbox table written in the same transaction as the change; a
  dispatcher job (worker, or a loop in the API in local mode, like cleanup) matches enabled
  automations and queues runs of kind `automation`.
- **Loop guard:** events caused by an automation's run don't trigger automations (origin
  recorded on the event); at most one run per automation at a time; the daily budget stops it.
- **Inbox:** `inbox_items` (`user_id`, `workspace_id`, `kind`, `ref`, `summary`, `read_at`):
  approvals waiting, findings, watch changes, finished background runs. `GET /v1/me/inbox`, a
  sidebar count, and email for approvals waiting and high-severity findings, batched per run
  (templates in `core/email_templates.py`). Per-person settings come with Phase 4.

## 10. Step 5: code

- **(you)** Register the GitHub App (D5): contents and pull requests read, metadata, webhooks
  for push, pull request, check suite; write access later for PR comments. Private key and
  app id in the secrets store, never in code or logs.
- `repo_connections`: `workspace_id`, `project_id`, `installation_id`, `repo_full_name`,
  `default_branch`. Installation tokens are minted per job and kept in memory only.
- `POST /v1/webhooks/github`, signature checked (HMAC), queues events into the outbox.
- **Checkout:** a shallow clone of the commit in the worker's temporary directory, deleted
  after the job; secrets-looking files (`.env*`, keys) are never read into prompts.
- **Code graph:** `code_files` (path, content hash, language) and `code_symbols` /
  `code_edges` (defines, imports, calls, tests) per repo and branch, from Tree-sitter
  (`tree-sitter-language-pack`). Only files whose hash changed are re-parsed. Modules link
  to project graph `module` nodes by path.
- **Tools:** `code_search(query)`, `read_code(path, lines)`, `blast_radius(paths or
  symbols, depth ≤ 3)` (callers, dependants, and the tests that cover them).
- **Commit review:** `commit.pushed` on the default branch or a PR branch → code graph update
  → blast radius → `reviewer.commit` → `finding[]` → inbox and email for high severity →
  Create issue / Fix now / Dismiss (a lesson). Skips commits that only touch docs or
  lockfiles; a daily budget per repo.
- **CI failures:** `ci.failed` → the failing job's log excerpt + blast radius → one scoped
  finding.

## 11. Step 6: Space

- Each workspace gets a **space**: a project row of kind `space` (one per workspace, key
  `SPACE`, hidden from project lists), so knowledge, chat, search, approvals, graph, and
  audit work unchanged.
- **Space instructions** (`space.md` in its knowledge) say how the space is organised; the
  documentation agent follows them.
- **Ideas:** conversations in the space; members start and join them. "Start a project from
  this idea" (owners and admins) creates the project and proposes its first documents and
  issues as one batch.
- The context pack of a project includes a short excerpt of the space's relevant notes
  (graph neighbours across the space and the project, same workspace only).
- **Comments with `@handle`** on documents: a comment thread on a section; mentioning an
  agent starts a run with the section as context; its change is proposed as usual.

## 12. Decisions

| # | Decision | Outcome |
|---|---|---|
| D1 | Standing `allow` rules vs "no agent write without approval" | **Decided:** owners approve standing rules; low-risk actions only; the CLAUDE.md rule is amended (§4.5) |
| D2 | Where contracts live | **Decided:** the workspace (Personal or Organisation), with per-project overrides |
| D3 | Search provider | Tavily (built for agents, simple pricing); Exa or Brave also fit |
| D4 | Quality evals | On demand with a key, not in CI |
| D5 | GitHub App | Register when step 5 starts; one app for sign-in and repos |
| D6 | Workspace vs organisation | **Decided:** fold organisations into workspaces; Personal or Organisation; project access for teams (§0) |

## 13. Sources

- [Introducing dots (OpenAI)](https://openai.com/index/introducing-dots/)
- [ChatGPT Space](https://chatgpt.com/features/space/), [Getting started with Space](https://help.openai.com/en/articles/20001549-getting-started-with-space-in-chatgpt)
- [ChatGPT workspace agents](https://help.openai.com/en/articles/20001143-chatgpt-workspace-agents-for-enterprise-and-business)
- [Deep Research Agents: A Systematic Examination and Roadmap](https://arxiv.org/abs/2506.18096)
- [Four open-source deep research agents, tested](https://www.digitalapplied.com/blog/open-source-deep-research-agents-2026-guide)
- [code-review-graph](https://github.com/tirth8205/code-review-graph)
- [Standardize project context with AGENTS.md and Agent Skills (Red Hat)](https://developers.redhat.com/articles/2026/07/27/standardize-project-context-agentsmd-and-agent-skills)
- [AI agents in 2026: tools, memory, evals, and guardrails](https://andriifurmanets.com/blogs/ai-agents-2026-practical-architecture-tools-memory-evals-guardrails)
