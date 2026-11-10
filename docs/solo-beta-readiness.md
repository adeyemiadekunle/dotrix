# Private solo beta: readiness

Phase 4 of the [solo-first product direction](solo-first-product-direction.md): what a private beta
for solo developers supports, what has been verified where, and what has not. A row says
**verified** only with evidence from the named environment; synthetic tests, local Docker runs and
accepted todos are not deployment evidence. Keep this page current as checks are run; it is the
list the beta is released against.

## Supported configuration

| Area | Supported in the beta | Notes |
| --- | --- | --- |
| Workspace | One personal workspace per account | Organisations are off (`DOTRIX_ORGANISATIONS`, the default on staging and production). Existing organisations keep their data and return when the setting is turned on. |
| Sign-in | Email and password, sign-in links, GitHub sign-in | Email verification, password reset and sign-in links need outgoing email (Sendly). |
| Account recovery | Password reset and sign-in link by email; signing out other browsers and the desktop app from Settings → Sessions | No two-factor authentication yet. |
| Starting a project | Explore an idea, Start a new codebase, Connect an existing repository | Repository creation on GitHub needs the GitHub App installed on the account; personal GitHub accounts create the repository on GitHub, then connect it. |
| GitHub | One GitHub App installation per account, one connected repository per project; PRs, checks, Juno's review on the PR, CI failures triaged | The App needs Contents, Pull requests, Checks (read), Actions (read), Issues (write) and the Check suite event. |
| Chat models (personal keys) | Anthropic, OpenAI, Google | Personal BYOK only: every run uses the person's own encrypted key, and nothing runs without one. Google works for DeepAgents conversations; fx chat on Google is not supported (libfx rejects Gemini's stream endings). |
| Chat runtime | DeepAgents (default), fx per conversation | fx has been checked live on Anthropic only. |
| Coding engines | Claude Code (Anthropic), Codex (OpenAI), OpenCode (Anthropic, OpenAI, Google, xAI, DeepSeek, Mistral, Groq, OpenRouter, NVIDIA), fx (OpenAI-compatible providers) | A session picks a model; the engine follows it. Each engine is pinned in the coding image. |
| Where coding runs | Cloud: Docker sandboxes on the worker with gVisor, or Docker Cloud sandboxes. Local: the desktop app or CLI runner in the person's own folder | Local turns run commands only when `sbx` (Docker Sandboxes) is installed; without it the tool only edits files. |
| Approvals | Manual, Accept edits, Auto; Nova's first handoff to Kai starts at once only in Auto | Changes to files CI runs wait for a person in every mode. |
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
- [ ] Backups: a snapshot of `pgdata` and `storagedata` taken and restored once.

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
- [ ] The CHANGELOG's Unreleased section turned into a version before the beta (`python scripts/release.py bump`), and What's new showing it in the desktop app.
- [ ] A short "Getting started" for beta participants: the supported configuration above, how to connect a key and GitHub, what Manual approval means, how to stop a run, and how to report a problem.

## Known limitations

What a beta participant should be told, with where each is tracked (CLAUDE.md's remaining work).

- **Organisations and teams** are off: no invites, members, roles or shared workspaces.
- **One person per key.** No retry on a provider's 429 beyond stopping the run with Continue; no per-workspace queue of runs.
- **Codes polls** for a turn's output rather than streaming it; usage per session and nested subagent events are not shown.
- **Local coding** runs commands only with `sbx` installed (checked against a fake `sbx`, not a real one); a folder without a remote gets a branch and diff, no PR.
- **Desktop app:** Windows only, unsigned; not yet run on a real Windows machine end to end.
- **fx chat** has run live on Anthropic only; Google is not supported on fx; OpenCode and fx on providers other than Anthropic and OpenAI have been checked against fake APIs, not paid models.
- **Chat across projects** has no steering, queued follow-ups, work modes or Continue after a model limit.
- **Search** indexes with the instructing person's key only where it has one; otherwise keyword search.
- **Repository knowledge** reads package.json, pyproject/requirements, Cargo and go.mod manifests; Gemfile, composer, Gradle and Maven are not read.
- **Settings "not available yet":** two-factor authentication, push notifications, deleting a workspace, changing its address, billing.
- **Not verified in production:** the Docker Cloud sandbox and the gVisor host, Juno's review posting against a real PR from the deployed host, the first fx turn through the platform's own sandbox, and every row above still unticked.
