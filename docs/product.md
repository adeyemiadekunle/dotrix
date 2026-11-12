# Product and release readiness

Maintained against `stage`, 2026-11-12. This is the current product contract and beta release checklist. [Architecture and agents](architecture.md) explains implementation boundaries; [README](../README.md) covers installation and development. Contributor rules remain in [CLAUDE.md](../CLAUDE.md) and [AGENTS.md](../AGENTS.md). A merged feature or passing synthetic test does not establish deployment readiness.

## Product direction

Dotrix helps a solo developer turn an idea or an existing GitHub repository into a planned, implemented and reviewed change:

**Idea or repository → understand → agree on scope → save knowledge and tasks → approve Kai → implement and check → Juno review → human merge and project update.**

Launch a focused private solo beta, learn from real use, then widen collaboration. Personal and organisation workspaces share one account and permission foundation. Organisations are hidden when `DOTRIX_ORGANISATIONS` is off; preserve their data, isolation and existing permissions. Do not remove features merely because they are outside the first release.

A project is the home for work. Support Explore an idea, Start a new codebase, and Connect an existing repository. An idea needs only a working title; GitHub is optional until code is needed. Tasks, documents and navigation work without a model key. Agents use the instructing person's encrypted provider key, with no platform or colleague key fallback. Provider charges and infrastructure costs are separate.

Keep Home, Projects, Chat, Codes, Tasks and Settings useful to one person. Hide team invitations, workload reports and organisation administration from personal workspaces. Defer enterprise controls, broad integrations, arbitrary agent identities and recursive teams until the core loop is dependable.

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
| J08: first workspace | The optional initial workspace choice defaults to Personal; Skip saves it. Organisation creation is explicit and feature-gated. A labelled stepper keeps saved state. | Concurrent/retried choices reuse the confirmed workspace; conflicts require review. Invitation/return paths and later project setup bypass registration choice. Personal-to-organisation conversion is retired; explicit project moves preserve permissions and privacy. |

Regression entry points are [web browser specs](../apps/web/e2e/) and [backend integration tests](../apps/backend/tests/integration/), including onboarding, project starts, repository creation/readiness, baseline review, publication, imports, coding and project readiness. Synthetic GitHub/model traffic establishes application behaviour; it does not verify external services or paid-model quality.

## Product decisions from the solo audit

The earlier feature audit was a repository assessment, not a removal approval or a production certification. Retain these decisions:

- Keep accounts, projects, lightweight tasks/knowledge, private Chat, linked Codes, provider settings, repository coverage and PR/check/review evidence.
- Refine onboarding and GitHub access explanations; verify all three intentions, safe retry/resume, missing-key states and personal workspace navigation.
- Verify specialist names, authorised connected-code access, Stop/Send, steering/queued input and Nova–Kai–Juno outcome provenance on both chat runtimes. Historical observations are reproduction leads, not claims that current code is still broken.
- Hide or defer team-first presentation, advanced reporting and complex automation from the solo release. Any removal needs a separate dependency, usage and migration assessment.
- Measure actual task completion, abandonment, recovery, cost and return usage during the beta before expanding scope or claiming savings.

## Demo and live presentation

Demo and live share Shell, session/message rows, coding panels and Settings presentation, with Geist Sans/Mono typography. Demo history is labelled sample data; edits stay local and connections are read-only. Missing sample files/reviews remain missing. Live accounts use workspace-scoped data and real empty states. Never replace an empty live account with fabricated seed history. Browser tests of samples, onboarding and model gates do not establish real GitHub installation or production readiness.

## Supported configuration

| Area | Supported in the beta | Notes |
| --- | --- | --- |
| Workspace | One personal workspace per account | Organisations are off (`DOTRIX_ORGANISATIONS`, the default on staging and production). Existing organisations keep their data and return when the setting is turned on. |
| Sign-in | Email and password, sign-in links, GitHub sign-in | Email verification, password reset and sign-in links need outgoing email (Sendly). |
| Account recovery | Password reset and sign-in link by email; signing out other browsers and the desktop app from Settings → Sessions | No two-factor authentication for people's accounts yet (the admin console has its own). |
| Starting a project | Explore an idea, Start a new codebase, Connect an existing repository | Repository creation on GitHub needs the GitHub App installed on the account; personal GitHub accounts create the repository on GitHub, then connect it. |
| GitHub | One GitHub App installation per account, one connected repository per project; PRs, checks, Juno's review on the PR, CI failures triaged | The App needs Contents, Pull requests, Checks (read), Actions (read), Issues (write) and the Check suite event. |
| Chat models (personal keys) | Anthropic, OpenAI, Google | Personal BYOK only: every run uses the person's own encrypted key, and nothing runs without one. Google works for DeepAgents conversations; fx chat on Google is not supported (libfx rejects Gemini's stream endings). |
| Chat runtime | DeepAgents (default), fx per conversation | fx has been checked live on Anthropic only. |
| Coding engines | Claude Code (Anthropic), Codex (OpenAI), OpenCode (Anthropic, OpenAI, Google, xAI, DeepSeek, Mistral, Groq, OpenRouter, NVIDIA), fx (OpenAI-compatible providers) | A session picks a model; the engine follows it. Each engine is pinned in the coding image. |
| Where coding runs | Cloud: Docker sandboxes on the worker with gVisor, or Docker Cloud sandboxes. Local: the desktop app or CLI runner in the person's own folder | Local turns run commands only when `sbx` (Docker Sandboxes) is installed; without it the tool only edits files. |
| Approvals | Manual, Accept edits, Auto; Nova's first handoff to Kai starts at once only in Auto | Changes to files CI runs wait for a person in every mode. |
| Storage | 1 GB of uploads per workspace by default (`DOTRIX_WORKSPACE_STORAGE_MB`), document originals and task attachments; Settings → Workspace shows the use | An upload that doesn't fit is refused; nothing is deleted. The operator sets a workspace's own limit in the admin console. |
| Operating it | The admin console: health of the worker, Redis, storage, email and the GitHub App; runs, failures by kind, cost by model, workspaces, audit; operator alert emails; owner and viewer admins with two-factor sign-in and an activity record | `deploy/migrate.sh` checks, backs up and applies database migrations on the server. See [deploy/README.md](../deploy/README.md). |
| Desktop app | Windows installer and self-updates | Unsigned (SmartScreen warns). macOS later. |
| Deployment | One VPS with Dokploy, `deploy/README.md` | Coding on the VPS requires gVisor (`DOTRIX_CODING_DOCKER_RUNTIME=runsc`) and a positive `DOTRIX_CODING_MAX_RUNS`. |

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

- [ ] `docker info` on the worker's daemon lists `runsc`; `DOTRIX_CODING_DOCKER_RUNTIME=runsc` is set and the API and worker start (they refuse an ordinary runtime).
- [ ] `uv run pytest apps/backend/tests/unit/test_coding_docker.py -v` passes on that host with the built coding image.
- [ ] One authorised coding turn on a disposable repository: the container's runtime recorded as `runsc`, the egress proxy the only way out (a request to another host from inside the sandbox is refused), the key never in the container's environment on Docker Cloud.
- [ ] Stop ends a running turn within seconds and leaves no container behind; a worker killed mid-turn leaves the run `recovery_required`, and Recover settles it from GitHub.
- [ ] Or, on Docker Cloud: the same turn, the network policy allowing only the model API host, the sandbox sleeping between turns and deleted after `DOTRIX_CODING_SLEEP_DAYS`.

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

What a beta participant should be told, with where each is tracked (CLAUDE.md's remaining work).

- **Organisations and teams** are off: no invites, members, roles or shared workspaces.
- **One person per key.** No retry on a provider's 429 beyond stopping the run with Continue; no per-workspace queue of runs.
- **Codes** shows recorded background task states, checks and command output. Token-by-token replies, aggregate session usage and fully nested runtime-native subagent events remain incomplete.
- **Local coding** runs commands only with `sbx` installed (checked against a fake `sbx`, not a real one); a folder without a remote gets a branch and diff, no PR.
- **Desktop app:** Windows only, unsigned; not yet run on a real Windows machine end to end.
- **fx chat** has run live on Anthropic only; Google is not supported on fx; OpenCode and fx on providers other than Anthropic and OpenAI have been checked against fake APIs, not paid models.
- **Chat across projects** has no steering, queued follow-ups, work modes or Continue after a model limit.
- **Search** indexes with the instructing person's key only where it has one; otherwise keyword search.
- **Repository knowledge** reads package.json, pyproject/requirements, Cargo and go.mod manifests; Gemfile, composer, Gradle and Maven are not read.
- **Settings "not available yet":** two-factor authentication for people's accounts, push notifications, deleting a workspace, changing its address, billing.
- **Storage:** 1 GB of uploads per workspace unless the operator raises it; two uploads at the same moment can pass the check together and go over by one file.
- **Not verified in production:** the Docker Cloud sandbox and the gVisor host, Juno's review posting against a real PR from the deployed host, the first fx turn through the platform's own sandbox, the admin console's two-factor sign-in and alert emails, `deploy/migrate.sh` on the real server, and every row above still unticked.

## Remaining delivery priorities

Production release gates come first: real host isolation, HTTPS/secrets, backups/restores, migrations, email/account recovery and the deployed Nova → Kai → Juno loop. Check each item above against a date, commit, environment and evidence link; leave unverified items open.

Next finish coding text streaming and session usage, deeper background event nesting, specialist memory export/retention, cross-project conversation controls, distributed limits and failure testing, and paid-provider coverage. Keep `DOTRIX_CODING_PARALLEL` off until the deployment validation in [Planning and parallel execution](architecture.md#planning-and-parallel-execution) passes.

Later work includes real `sbx`/Windows verification, desktop signing/macOS, code graphs and blast radius, app previews/MCP expansion, additional dependency manifests, workspace knowledge, account two-factor authentication, notifications/connectors and enterprise features. Existing capabilities should be checked before implementing an old roadmap item again: GitHub Issues snapshot imports, board check evidence and background task rendering already exist.

The detailed engineering queue and historical implementation evidence remain in [CLAUDE.md](../CLAUDE.md#remaining-work-by-priority-2026-10-30) and [audit plans](../plans/README.md). Completed audit plans are historical records, not a second product roadmap.
