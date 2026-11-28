# Product and release readiness

Maintained against `stage`, 2026-11-21. This is the current product contract and beta release checklist. [Architecture and agents](architecture.md) explains implementation boundaries; [README](../README.md) covers installation and development. Contributor rules remain in [CLAUDE.md](../CLAUDE.md) and [AGENTS.md](../AGENTS.md). A merged feature or passing synthetic test does not establish deployment readiness.

## Product direction

Dotrix helps a solo developer turn an idea or an existing GitHub repository into a planned, implemented and reviewed change:

**Idea or repository → understand → agree on scope → save knowledge and tasks → approve Kai → implement and check → Juno review → human merge and project update.**

Launch a focused private solo beta, learn from real use, then widen collaboration. Personal and Team workspaces share one account. A Team workspace is for project management. Owners and Admins create issues and assign them to people who can access the project. Members can use Chat and Codes on their assigned tasks and retain ownership of the work. A Personal workspace owner can assign work to Kai. Team workspace availability follows `DOTRIX_TEAMS`. Do not remove features merely because they are outside the first release.

A project is the home for work. Support Explore an idea, Start a new codebase, and Connect an existing repository. An idea needs only a working title; GitHub is optional until code is needed. Tasks, documents and navigation work without a model key. Agents use the instructing person's encrypted provider key, with no platform or colleague key fallback. Provider charges and infrastructure costs are separate.

Keep Home, Projects, Chat, Codes, Tasks and Settings useful to one person. Hide team invitations, workload reports and Team workspace administration from personal workspaces. Defer enterprise controls, broad integrations, arbitrary agent identities and recursive teams until the core loop is dependable.

## Getting started

### 1. Create your account

Sign up at the app with your email (you'll get a link to verify it) or with GitHub. You land in your
own private workspace, and onboarding walks you through a project, GitHub and your model.

Forgot your password? **Forgot password** on the sign-in page emails a reset link, and **Email me a
sign-in link** signs you in without one. Settings → Sessions lists where you're signed in and signs
out any of them.

### 2. Connect your model key

Open **Account → Your models** and add a key from **Anthropic**, **OpenAI** or **Google**.

- Your key is encrypted, and only ever used for runs you start. dotrix doesn't resell tokens and has
  no key of its own to fall back on, so agents don't run until you add one.
- Projects, tasks and documents all work without a key.
- Pick your default model there too. Each conversation and coding session can use a different one.
- When a provider stops a run at its limit, the run says so and **Continue** picks it up from where it
  stopped, now or once the limit resets.

### 3. Start a project

Onboarding offers three starting points:

- **Explore an idea:** a draft project with no repository, dates or finished plan.
- **Start a new codebase:** say what you're building, then create its repository on GitHub.
- **Connect an existing repository:** dotrix takes an inventory of it, and Echo can explain it in a
  wiki you review.

To work on code, install the **dotrix GitHub App** when onboarding asks and pick the repository. Kai
never holds a GitHub token, never pushes to your default branch, and opens a pull request for you to
merge.

### 4. Talk to Nova, and hand building to Kai

Chat is where you talk to **Nova**, who brings in Lyra (product), Orion (architecture), Vega
(research), Juno (review) and Echo (documentation) when the work needs them. Each message has a
mode:

- **Discuss** to think things through, **Plan** to save a plan, **Build** to hand it to Kai,
  **Review** to look at what Kai did.

**Kai** codes in **Codes**, below Chat: in a cloud sandbox, or on your own computer with the desktop
app (Windows). Each session has its own branch and pull request. Juno reviews the pull request on
GitHub, and when CI fails, Juno reads the logs and **Ask Kai to fix** starts a follow-up.

### 5. Decide what needs you

The approval mode is picked in the message box:

- **Manual:** every change waits for you, with its diff. Kai's turns wait to start, and again before
  they're pushed.
- **Accept edits:** what you asked for goes through, recorded as approved by you.
- **Auto:** goes further, and checkpoints don't pause.

Whatever the mode, changes to files your CI runs wait for you, Nova's first hand-off to Kai waits in
your Inbox unless you're in Auto, and **you merge every pull request yourself**. A pushed turn can be
reverted from Codes.

### 6. Stop anything

**Stop** ends a reply in Chat or a coding turn in Codes, and cancels anything you queued. A stopped,
rejected or interrupted run shows exactly that: dotrix never reports a success or a pull request that
didn't happen. A coding turn cut off by a restart is checked against GitHub and either adopted, run
again, or left for you under **Check and recover**.

### 7. Tell us what broke

**Help & resources → Report a problem** opens a new issue on GitHub. Issues are **public**, so
describe what happened without keys, private code, or anything you wrote in dotrix.


The public introduction is [dotrix.cc/#start](https://dotrix.cc/#start), linked from Help & resources → Getting started. Supported configurations and outstanding checks follow below.

## Delivered product journeys

J01–J08 describe implemented repository journeys, with deterministic regression coverage. The identifiers remain stable for engineering references. Their deployment checks are still separate.

| Journey | Current behaviour | Evidence to preserve |
| --- | --- | --- |
| J01: shared setup | Signup and later New project use the same server-confirmed onboarding flow. Invited members join their intended workspace/project first. | Saved workspace/project IDs survive refresh, sign-in and GitHub redirects. Uncertain saves refresh and offer explicit reuse; no blind duplicate creation. |
| J02: three intentions | Ideas start without GitHub; new codebases save a goal before repository setup; existing repositories can be connected to saved projects. | Saved project source wins over URL hints. Later attachment preserves tasks, knowledge and conversations. Nova starters are editable drafts, never automatic model calls. |
| J03: first reviewed PR | Organisation repository creation confirms owner/name/visibility and rechecks installation rights. Personal GitHub uses create with README → grant App access → refresh/select/connect. | Creation and attachment are separate. An uncertain creation response requires inspecting available repositories, not automatic retries. Live readiness requires a committed default branch before coding admission; empty repositories are not automatically initialised. The validated base is pinned; failed later fetching stops before model execution. |
| J04: existing-repository baseline | Inventory → cited wiki → human goals/corrections → confirmation of the exact evidence revision. | Missing citations/inventory, stale pages, changed human context or known newer commits invalidate confirmation. Review is a knowledge-editor action with acknowledged limits, not implementation approval or proof of complete understanding. |
| J05: explicit publication | A person previews and edits selected content from their completed private reply into shared requirements, decisions, research or an unassigned To do task. | Current permissions, version checks and retry receipts apply. Optional task/document links are same-project and version-pinned. Decision supersession preserves old text/history. Shared destinations never inherit private transcript links or start coding. |
| J06: GitHub backlog import | A human reviews and selects up to 50 issues per preview page from the connected repository. Imports are one-time snapshots into Tasks. | Open issues map to Backlog/To do; closed-completed issues to Done. No comments, attachments, milestones, Projects or source relationships. Recheck source revisions and permissions before one atomic batch. Stable source IDs and tombstones prevent duplicate or deleted-task recreation; later GitHub edits never overwrite tasks. |
| J07: readiness and next action | Onboarding, Overview and empty task views share saved, requester-specific readiness. | A URL is not a connection; a connection is not live execution admission; a saved key is not verified provider access. Key changes invalidate older success evidence. Readiness makes no external calls or writes and never blocks manual project work. |
| J08: first workspace | The optional initial workspace choice defaults to Personal; Skip saves it. Team workspace creation is explicit and feature-gated. A labelled stepper keeps saved state. | Concurrent/retried choices reuse the confirmed workspace; conflicts require review. Invitation/return paths and later project setup bypass registration choice. Personal-to-Team conversion is retired; explicit project moves preserve permissions and privacy. |

Regression entry points are [web browser specs](../apps/web/e2e/) and [backend integration tests](../apps/backend/tests/integration/), including onboarding, project starts, repository creation/readiness, baseline review, publication, imports, coding and project readiness. Synthetic GitHub/model traffic establishes application behaviour; it does not verify external services or paid-model quality.

## Product decisions from the solo audit

The earlier feature audit was a repository assessment, not a removal approval or a production certification. Retain these decisions:

- Keep accounts, projects, lightweight tasks/knowledge, private Chat, linked Codes, provider settings, repository coverage and PR/check/review evidence.
- Refine onboarding and GitHub access explanations; verify all three intentions, safe retry/resume, missing-key states and personal workspace navigation.
- Verify specialist names, authorised connected-code access, Stop/Send, steering/queued input and Nova–Kai–Juno outcome provenance on both chat runtimes. Historical observations are reproduction leads, not claims that current code is still broken.
- Hide or defer team-first presentation, advanced reporting and complex automation from the solo release. Any removal needs a separate dependency, usage and migration assessment.
- Measure actual task completion, abandonment, recovery, cost and return usage during the beta before expanding scope or claiming savings.

## Demo and live presentation

Demo and live share Shell, session/message rows, coding panels and Settings presentation, with Geist and Geist Mono typography. Demo history is labelled sample data; edits stay local and connections are read-only. Missing sample files/reviews remain missing. Live accounts use workspace-scoped data and real empty states. Never replace an empty live account with fabricated seed history. Browser tests of samples, onboarding and model gates do not establish real GitHub installation or production readiness.

## Supported configuration

| Area | Supported in the beta | Notes |
| --- | --- | --- |
| Workspace | One personal workspace per account | Team workspaces are off (`DOTRIX_TEAMS`, the default on staging and production). Existing Team workspaces keep their data and return when the setting is turned on. |
| Sign-in | Email and password, sign-in links, GitHub sign-in | Email verification, password reset and sign-in links need outgoing email (Sendly). |
| Account recovery | Password reset and sign-in link by email; signing out other browsers and the desktop app from Settings → Sessions | No two-factor authentication for people's accounts yet (the admin console has its own). |
| Starting a project | Explore an idea, Start a new codebase, Connect an existing repository | Repository creation on GitHub needs the GitHub App installed on the account; personal GitHub accounts create the repository on GitHub, then connect it. |
| GitHub | One GitHub App installation per account, one connected repository per project; PRs, checks, Juno's review on the PR, CI failures triaged | The App needs Contents, Pull requests, Checks (read), Actions (read), Issues (write) and the Check suite event. |
| Chat models (personal keys) | Anthropic, OpenAI, Google | Personal BYOK only: every run uses the person's own encrypted key, and nothing runs without one. Google works for DeepAgents conversations; fx chat on Google is not supported (libfx rejects Gemini's stream endings). |
| Chat runtime | DeepAgents (default), fx per conversation | fx has been checked live on Anthropic only. |
| Coding engines | Claude Code (Anthropic), Codex (OpenAI), OpenCode (Anthropic, OpenAI, Google, xAI, DeepSeek, Mistral, Groq, OpenRouter, NVIDIA), fx (OpenAI-compatible providers) | A session picks a model; the engine follows it. Each engine is pinned in the coding image. |
| Where coding runs | Cloud: Docker Cloud sandboxes in staging and production, OpenShell in development. Local: the desktop app or CLI runner in the person's own folder | Local turns run commands only when `sbx` (Docker Sandboxes) is installed; without it the tool only edits files. |
| Approvals | Manual, Accept edits, Auto; Nova's first handoff to Kai starts at once only in Auto | Changes to files CI runs wait for a person in every mode. |
| Storage | 1 GB of uploads per workspace by default (`DOTRIX_WORKSPACE_STORAGE_MB`), document originals and task attachments; Settings → Workspace shows the use | An upload that doesn't fit is refused; nothing is deleted. The operator sets a workspace's own limit in the admin console. |
| Operating it | The admin console: health of the worker, Redis, storage, email and the GitHub App; runs, failures by kind, cost by model, workspaces, audit; operator alert emails; owner and viewer admins with two-factor sign-in and an activity record | `deploy/migrate.sh` checks, backs up and applies database migrations on the server. See [deploy/README.md](../deploy/README.md). |
| Desktop app | Windows installer and self-updates | Unsigned (SmartScreen warns). macOS later. |
| Deployment | One VPS with Dokploy, `deploy/README.md` | Coding runs on Docker Cloud (`DOTRIX_CODING_SANDBOX=docker-cloud`, the account, token and published image) with a positive `DOTRIX_CODING_MAX_RUNS`; no sandboxes run on the VPS. |

## Readiness checks

Each check names the environment it must run in. **Local** means a developer machine or CI
(synthetic GitHub and models); **production** means the deployed host with the real GitHub App
and a real model key, on a disposable repository. Record the date, the commit and where the
evidence lives when a check passes.

### Deployment (production)

- [ ] A domain with HTTPS for the web app, `DOTRIX_APP_URL` set to it, `DOTRIX_ENV=production`, `DOTRIX_ENCRYPTION_KEY` and `DOTRIX_JWT_SECRET` from a secrets manager, Postgres and Redis reachable only inside the compose network.
- [ ] `GET /health/ready` answers from the deployed API; a redeploy of the API while a chat run works loses nothing (the worker finishes it).
- [ ] The GitHub App's callback and webhook URLs point at `DOTRIX_APP_URL`; a push to a connected repository reaches the webhook (the audit log records the sync).
- [ ] Outgoing email delivers: a verification email, a password reset and a sign-in link each arrive from `DOTRIX_EMAIL_FROM`.
- [ ] Backups: a snapshot of `pgdata` and `storagedata` taken and restored once; `deploy/migrate.sh backup` taken and restored once into a scratch database.
- [ ] Migrations: `deploy/migrate.sh check` passes after the deploy; one recovery rehearsed (a failed `migrate`, then `IMAGE=dotrix-backend:<version> deploy/migrate.sh`).
- [ ] Storage: the usage query in `deploy/README.md` run before the first deploy with the limit; no workspace over it.
- [ ] Admin console: the first owner created, two-factor set up, `DOTRIX_ADMIN_BOOTSTRAP_TOKEN` removed; a second admin invited by email and signed in; the Overview shows every dependency OK.
- [ ] Alerts: stopping the worker sends one alert email to `DOTRIX_ALERT_EMAILS` on the second check, and one "cleared" email after it's back.

### Sandbox isolation (production)

- [ ] `DOTRIX_CODING_SANDBOX=docker-cloud` with `DOTRIX_DOCKER_CLOUD_ID`, `DOTRIX_DOCKER_CLOUD_PAT` and `DOTRIX_CODING_IMAGE` (a published registry tag); the API and worker start.
- [ ] One authorised coding turn on a disposable repository: the sandbox's network policy allowing only the model API host and the session's hosts (a request to another host from inside the sandbox is refused and reported), the key never in the sandbox's environment.
- [ ] Stop ends a running turn within seconds and leaves no sandbox running; a worker killed mid-turn leaves the run `recovery_required`, and Recover settles it from GitHub.
- [ ] The sandbox sleeps between turns, wakes for the next, and is deleted after `DOTRIX_CODING_SLEEP_DAYS`.

### Accounts and recovery (production)

- [ ] Sign up, verify the email, sign out, reset the password, sign back in.
- [ ] A sign-in link works once and is refused the second time.
- [ ] GitHub sign-in on a fresh account creates its personal workspace and lands on onboarding.
- [ ] Settings → Sessions signs out another browser, which loses access at once.
- [ ] A refresh token reused after rotation signs that browser out (the API treats it as theft).

### Provider and GitHub setup (production)

- [ ] Each supported chat provider: a key saved in Account → Your models, its models listed, one conversation completed, its usage shown; a wrong key reported as such without saving it.
- [ ] A provider limit (429) shown as "stopped at its model's limit" with Continue, not as a failure.
- [ ] GitHub App install from onboarding returns to the saved project; the repository list refreshes; connecting a repository starts a sync and an inventory.
- [ ] Repository creation: a personal account's path (create on GitHub, grant the App, refresh, connect) and an organisation account's path (created by the App after confirmation), each once.

### The core loop (production, one disposable repository)

- [ ] Discuss → Plan → Build in one conversation: Nova delegates to a specialist by name (Lyra, Orion, Vega, Juno, Echo), the plan is saved, "Build this plan" creates Kai's approval notification, approving it in the Inbox starts Kai.
- [ ] Kai's turn: steps and command output visible in Codes, the diff per file, the branch pushed, the PR opened by the App, the commit's checks shown for that exact commit.
- [ ] Juno's review posted on the PR as a comment (never an approval), its findings on their diff lines in Codes.
- [ ] The outcome returns to the originating conversation (Nova's summary names the PR and the review); a different conversation cannot read it.
- [ ] A failing CI run on the PR starts Juno's triage once, shown on the PR and in Codes with "Ask Kai to fix".
- [ ] Stop mid-turn, a rejected approval, and a turn whose worker was killed each show their true state; no success or PR is invented.
- [ ] Steering a running Nova turn: the steer is accepted and changes the reply; a queued follow-up runs after the turn.
- [ ] A merge is done by the person on GitHub; the task stays open until they close it.

### Failure handling and limits (local, then production)

- [ ] Model limit mid-reply: the run stops, says so, and Continue resumes from the checkpoint (local: scripted model; production: a real 429).
- [ ] The worker restarted mid-chat-run: the run resumes within about two minutes under a new attempt, asks before any change, and tool calls the cut-off attempt left are not repeated.
- [ ] A coding run's lease lapses: `recovery_required` within about two minutes; Recover adopts the PR when the push landed.
- [ ] Usage: each run's tokens and cost shown; Codex and fx priced from their tokens; a run with missing usage marked incomplete rather than free.

### Support paths

- [x] A way to report a problem from the app: Help & resources → Report a problem opens a new issue on the repository (public), 2026-11-09.
- [ ] The CHANGELOG's Unreleased section turned into a version before the beta, and What's new showing it in the desktop app. The 0.2.0 version bump is recorded on stage; verify the release workflow/tag on main and What's new in an installed app before marking this complete.
- [x] A short "Getting started" for beta participants: the supported configuration, connecting a key and GitHub, what Manual approval means, how to stop a run, and how to report a problem. On the public site at [dotrix.cc/#start](https://dotrix.cc/#start), linked from the app's Help & resources → Getting started, and in full at [Getting started](#getting-started), 2026-11-12.

## Known limitations

What a beta participant should be told. Each is tracked in the [Roadmap](#roadmap).

- **Team workspaces** are off: no invites, members, roles or shared workspaces.
- **One person per key.** No retry on a provider's 429 beyond stopping the run with Continue; no per-workspace queue of runs.
- **Codes** shows Kai's reply text as it streams (up to 4,000 characters on fx turns), background tasks and helpers, checks and command output. Aggregate session usage and fully nested runtime-native subagent events remain incomplete.
- **Local coding** runs commands in a native sandbox for fx and Claude Code (Linux Bubblewrap, tested; macOS Seatbelt, Windows AppContainer and WSL 2, implemented but not yet checked on real machines), in Codex's own workspace sandbox, or in `sbx` (checked against a fake `sbx` only). OpenCode edits files only, without `sbx`. A folder without a remote gets a branch and diff, no PR.
- **Desktop app:** Windows only, unsigned; not yet run on a real Windows machine end to end.
- **fx chat** has run live on Anthropic and NVIDIA; Google is not supported on fx; OpenCode and fx on providers other than Anthropic and OpenAI have been checked against fake APIs, not paid models.
- **Chat across projects** has no steering, queued follow-ups, work modes or Continue after a model limit.
- **Search** indexes with the instructing person's key only where it has one; otherwise keyword search.
- **Repository knowledge** reads package.json, pyproject/requirements, Cargo and go.mod manifests; Gemfile, composer, Gradle and Maven are not read.
- **Settings "not available yet":** two-factor authentication for people's accounts, push notifications, deleting a workspace, changing its address, billing.
- **Storage:** 1 GB of uploads per workspace unless the operator raises it; two uploads at the same moment can pass the check together and go over by one file.
- **Not verified in production:** the Docker Cloud sandbox, Juno's review posting against a real PR from the deployed host, the first fx turn through the platform's own sandbox, the admin console's two-factor sign-in and alert emails, `deploy/migrate.sh` on the real server, and every row above still unticked.

## Roadmap

This is the only list of open work. It merges the solo-beta roadmap, the move to the Kai runtime (`adeyemiadekunle/kai-runtime`, the private fork of fx), CLAUDE.md's coding-agent plan and remaining work by priority, the platform-support work in CLAUDE.md, and the open phase of [plan 046](../plans/046-coding-workspaces.md). Other files point here rather than keeping their own list. The runtime's own phases and evidence live in its [migration plan](https://github.com/adeyemiadekunle/kai-runtime/blob/main/docs/DOTRIX_KAI_MIGRATION_PLAN.md). The [audit plans](../plans/README.md) are done and kept as historical records.

Decided 2026-11-21: **the beta launches with Kai's runtime as the default engine for new Chat and Code sessions.** Tick an item only with a date, commit, environment and evidence link. Implemented but unverified work stays open. "(you)" marks work that needs the owner rather than code.

### Where the Kai runtime migration stands (reviewed against CHANGELOG, 2026-11-28)

| Runtime phase | State |
| --- | --- |
| 0. Released fx 0.0.17 baseline | Done |
| 1. Shared execution contract and saved-state compatibility | Done. Sessions saved by libfx 0.0.16 and every earlier fork build still read. |
| 2. Provider capabilities and separate Chat and Code policies | Built. Live checks: NVIDIA only. Anthropic, OpenAI and Google on paid models are open. |
| 3. Chat on the fork's libfx | Done: `@kunemi-group/kai@0.0.18-kai.2`, the default for compatible providers. |
| 4. Cloud and local coding on the fork's fx | Done: `0.0.18-kai.2` is pinned in the coding image and is the default for compatible models. A paid turn in a Docker Cloud sandbox is open. |
| 5. Workers, skills, browser and background tasks | Done: worker profiles and limits, pinned skills, the Browser pane, background tasks, and helpers on every engine. |
| 6. Kai by default; legacy engines retired | First half mostly done: fx is the default and the rollback switches exist. Paid checks, the comparison, the full journey and a live rollback rehearsal are open. The second half comes after the beta. |
| 7. Kai branding and final names | After the beta |

### Closed in this review

These open items are done according to `CHANGELOG.md` (Unreleased and 0.4.0). Real-machine or paid-model checks that are still missing are listed further down.

- [x] **fx as the default** for new Chat conversations and for Code sessions on every model fx can run. Existing conversations and sessions keep their recorded runtime (`engine_for`, `choose_agent`). This was step 4 of Kai by default.
- [x] **Rollback tooling:** `DOTRIX_CHAT_DEFAULT_RUNTIME=deepagents`, `DOTRIX_CODING_AGENT=legacy`, the [rollback runbook](runbooks/kai-runtime-rollback.md), and D7 cross-version recovery tests. This was step 5, apart from the live rehearsal.
- [x] **Code streams Kai's reply text while a turn runs** (up to 4,000 characters on fx turns), replaced by the final summary at the end.
- [x] **Helpers (subagents) on every coding engine.** They are listed with Kai's background tasks while they work. Kai's commands also keep running between turns on fx.
- [x] **Local fx sessions resume.** `.fx` state is kept beside the managed worktree and `profile_digest` is checked. A follow-up keeps its bridge port, so it no longer starts a new conversation.
- [x] **Native local isolation on macOS and Windows is implemented.** macOS uses Seatbelt and Windows uses AppContainer with a Job Object for fx and Claude Code. Windows fx runs in WSL 2 Bubblewrap. Standalone CLI builds for Linux x64/arm64 and macOS arm64 bundle fx and, on Linux, Bubblewrap. Real-machine checks are open, see below.
- [x] **Several local turns at once** per runner (`--parallel`), and a network allowlist for commands in the native sandbox (`DOTRIX_CODING_NETWORK_ALLOW`).
- [x] **Plan 046 phase 4:** cloud Build turns checkpoint and restore unpublished edits after sandbox loss. Checking it on a real provider is open.
- [x] **The Live models workflow** (`.github/workflows/live.yml`) runs Nova and Kai on a chosen provider with keys from the `live-models` environment.
- [x] **Codex on a real model** (GPT-5.5, 2026-10-31). This closes "Verify first" in the old coding plan.
- [x] **GitHub Issues import** (J06) and **board check evidence** (J05). These close those parts of the old P1 and P3 lists.

### 1. Before the beta

Two tracks that can run side by side. The beta opens when both are done.

**Kai by default (runtime phase 6, first half).**

1. Paid-model checks on fx for Chat and Code: Anthropic and OpenAI through the Live models workflow, and a paid turn in a Docker Cloud sandbox. This is also the first fx turn through the platform's own sandbox. Either check Google on fx chat again (kai.2 parses Gemini's tool-call stream, but Dotrix doesn't offer Google for fx yet) or keep it listed as unsupported.
2. Set acceptance thresholds, then compare. Run fixed tasks on fx and on the earlier defaults (DeepAgents; Claude Code, Codex, OpenCode) and measure task success, latency, cost, recovery and human intervention.
3. The full journey on fx: Nova → Kai → Juno, with a denied action, a Stop, a worker restart and a pending approval kept across that restart.
4. Rehearse rollback on the deployed host with the switches and runbook above: route new work back to the earlier defaults and drain or recover active runs on their recorded runtime.

**Network policy for Kai's sandboxes.** One policy, in one format, for the cloud and local runners (Settings → Environments & network).

- [x] One network policy (2026-11-28, synthetic tests only): the workspace's optional limit, each project's choice within it, the choice pinned per coding session for cloud and local turns, and the local runner's `DOTRIX_CODING_NETWORK_ALLOW` able only to narrow it (`dotrix_engine/network_policy.py`, `coding/network.py`, `network_allow.for_turn`).
- [x] One sandbox per environment (2026-11-28): Docker Cloud in staging and production, OpenShell in development; the Docker sandbox (containers and an egress proxy on the worker's Docker, gVisor when deployed) is removed. OpenShell now takes the session's hosts in its policy (TLS relayed as is, for any program), since it already keeps the model key out.
- [ ] OpenShell with project hosts on a real gateway: the policy's `tls: skip` endpoints, `**.domain` wildcards and the `/**` binary rule follow OpenShell's schema reference (v0.1.10) and haven't run on a gateway.
- [ ] Docker Cloud's network policy on a real account: exact hosts, `*.domain`, `host:port` entries and the blocked-host report.

**Variables and secrets for Kai's sandboxes.** Per project, in its Environment beside the network policy; a session keeps its environment's version. Local turns never receive cloud secrets.

1. [x] Variables (2026-11-28, synthetic tests only): non-secret `KEY=value` pairs in the project's Environment, in `.env` format in the "Edit environment" form, shown in the brief and set for setup, Kai's commands and verification on cloud turns. Names the sandbox or tools use, and names that look like secrets, are refused.
2. [x] Host secrets (2026-11-28, synthetic tests only): a credential for one exact host in the project's network policy, added outside the sandbox to that host's requests in a header (Authorization and `Bearer ` by default), so the sandbox only ever holds a placeholder in the variable the secret is named after. Docker Cloud stores each as a custom secret injected into its host's requests; OpenShell attaches a provider per secret from a profile made for the turn, and the host goes through OpenShell's inspecting proxy rather than the relayed endpoints. Write-only, encrypted, audited without values; a session pins names and hosts, each turn reads the current value (a rotated token reaches running sessions), and a secret whose host changed or left the network policy is left out with a step saying so. The local sandbox, people's computers and parallel builds refuse or never receive them.
   - [ ] On a real OpenShell gateway (the per-turn profile, `auth_style`, an inspected endpoint beside relayed `**.domain` ones) and a real Docker Cloud account (custom injection to a non-model host, `host:port`).
   - [x] Workspace-shared secrets (2026-11-28, synthetic tests only): kept once in Settings → Environments & network (Workspace limit), within the workspace's limit when it has one; a project uses one only by referencing it by name in its Secrets, with its host in the project's network access. Each turn reads the shared secret's current value, so rotating it once reaches every project; deleting it leaves references listed as missing and turns go on without it.
3. [x] Setup-only secrets (2026-11-28, synthetic tests only): a project's own secret or a reference to a shared one, marked "Only for the setup script", goes to a fresh sandbox only when its setup script runs and is removed (the Docker secret deleted and checked gone, the OpenShell provider detached) before Kai starts; a failed removal stops the turn, and Kai's brief never names it. Not yet on a real gateway or account: OpenShell's `sandbox provider detach`, a deleted Docker secret's injection stopping at once, and waking a Docker sandbox whose stored secrets include a deleted one. On OpenShell a setup-only secret's host is reachable only while setup runs (its provider supplies the endpoint).

**Production release gates.**

- Every unticked item in [Readiness checks](#readiness-checks): HTTPS and secrets (you), sandbox isolation (Docker Cloud on a real account), backups and restores, migrations, email and account recovery, provider and GitHub setup, and failure handling. Run the core loop check on the deployed host with fx as the default.
- Turn the CHANGELOG's Unreleased section into a version and check What's new in an installed desktop app (Support paths).

### 2. During the beta

**Measure.** Task completion, abandonment, recovery, cost and return use, before widening scope or claiming savings. Measure quality and cost on real conversations before choosing model tiers.

**Code**
- Usage per session.
- Runtime-native subagent events nested inside the turn's steps. Today helpers are listed with background tasks.
- Helpers for local fx turns. They're off today because a helper's tool calls never reach the runner's approval check.
- [Plan 046](../plans/046-coding-workspaces.md) phase 5: continue a session in the cloud or locally from its published branch. Phase 4 also needs a check on a real provider, environment verification and dependency caching.
- Keep `DOTRIX_CODING_PARALLEL` off until the deployment validation in [Planning and parallel execution](architecture.md#planning-and-parallel-execution) passes: the paid engines under the read-only Plan wrapper, crash, recovery and cancellation under load, and Docker Cloud/OpenShell compatibility.
- PRs: a PR check that rejects `.dotrix/` in PRs from elsewhere, and the Reviewer's findings kept in `reviews/` (FR-22).

**Chat**
- fx chat changes and approvals on real models, and distributed failure testing.
- Specialist memory: forget/export and retention controls, and native long-lived fx specialist sessions.
- Conversations across projects: steering, queued follow-ups, work modes, and Continue after a model limit.
- Work modes: hidden specialists' activity as a compact timeline, a Review that shows diffs and checks inline, and Undo for chat changes that went through.

**Limits and keys**
- Several people on one key (proposed): retry on a provider's 429 with backoff, a per-workspace limit on runs at once with the rest queued, and usage per person in Settings → Models.
- Distributed per-workspace limits. Today the active-turn semaphore and the warm cache are per worker process.
- Search: pass the instructing person's key to embedding jobs.

**Verify what's implemented (keep cloud and local evidence separate)**
- Local: the macOS Seatbelt, Windows AppContainer and WSL 2 paths, Codex, the installed CLI, and the desktop Browser controls and Stop on real macOS and Windows machines. The Claude Code and fx namespace paths in the actual Electron app on Linux. Safe OAuth/subscription credential relaying for Claude Code and fx.
- OpenCode's local shell: add an enforced native boundary, or validate the `sbx` path on each host it supports. Never lift the `bash` denial without a replacement boundary.
- Cloud: live NVIDIA OpenCode and fx coding and browser tests, paid turns on the engines' other providers, and the OpenShell profiles on a real gateway.
- The delivered J01–J08 journeys in the target environment, with live GitHub and model evidence recorded separately from synthetic tests.

**Web**
- One data path: move the sample workspace's own data and Settings' saves (`data/account.ts`) to Query mutations.
- Rewrite the parked browser tests (admin, research, pipelines, the signed-out redirect, document upload).

### 3. After the beta

- **Retire legacy engines (runtime phase 6, second half).** Remove DeepAgents, Claude Code, Codex and OpenCode as fallbacks once parity and rollback hold, every active session and saved journal is accounted for, and local coding has a verified sandbox on each supported OS.
- **Kai branding (runtime phase 7).** Rename `fx`, `libfx`, `FX_*`, `.fx` and saved runtime identifiers, with aliases and imports that are tested. Until then they keep their names.
- **Local sandboxes and packaging:** real `sbx` templates, sign-ins, cancellation and browser reachability, plus an fx template if that route is needed. Windows signing and real-machine release checks. macOS and Linux desktop packaging, updates and notarization.
- **Running apps and MCP (old phase D):** the dotrix MCP server (board, documents, graph) over HTTP outside the sandbox, with a per-turn credential the sandbox never holds. Dev servers and preview through the platform, a live cloud browser view in Code, `sbx` turns reaching the desktop's Browser server, and a real model through `app_start`.
- **Local-file projects (old phase E):** a bare repo per project at setup, so a folder without a remote gets a PR path.
- **Code graph:** Tree-sitter files, symbols, imports, calls and tests, `code.blast_radius`, background commit and CI review, blast radius and tests to run in coding briefs, and automations on PR and CI events.
- **Repository knowledge:** more manifests (Gemfile, composer, Gradle, Maven), freshness of the context packet's pages in chat answers, and evaluating the discovery run on a real model.
- **Accounts and notifications:** Google sign-in (you: the OAuth client), two-factor authentication for people's accounts, and branded email templates. The daily briefing by email, Slack (FR-14), approving from email or Slack, and an optional second approver (FR-36).
- **Settings still "not available yet":** push notifications, deleting a workspace, changing its address, billing.
- **CLI:** `dotrix models`, and push from the local mirror (FR-18), with local `.dotrix/` edits going through approval.
- **Chat research sites (optional):** a per-workspace list of sites Nova's and Kai's web research may or may not read, in the network policy's format, beside it in Settings. It controls what agents read through the platform's fetcher, not where sandboxed commands may send data.
- **Measurement and observability:** `dotrix eval --live`, tracing agent runs, usage dashboards, and a workspace-wide default model (decision needed).
- **Later:** workspace knowledge (Space) and a standalone Ideas system; "Propose change" and "Fix now" on results, with a severity rubric; more graph node kinds; updating a repo's `AGENTS.md` / `CLAUDE.md` as a coding session; a design folder and Figma connector; sprints, SSO/SCIM, custom roles, billing, Drive/Notion/Confluence, GitLab, custom workflows, Jira and Linear imports, per-project folder access, invites to people without an account, and teams and enterprise features. Check what exists before building an old roadmap item again.
