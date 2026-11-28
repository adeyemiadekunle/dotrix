# Live and production checks

Every check that needs something the unit, integration and browser tests can't give: a paid model, a real
sandbox account or gateway, a real Windows or macOS machine, the packaged desktop app, or the deployed
host. CI and a developer's machine use scripted models and fakes of Docker Cloud, OpenShell and `sbx`;
passing those tests doesn't tick anything here.

This page is the one list of these checks. The [Roadmap](product.md#roadmap) names the open work and
points here for how to check it; the [readiness checks](#readiness-checks) the beta needs are at the end.

## How to record a check

Tick a box only with all four: the **date**, the **commit** (or released version), the **environment**
(provider and model, sandbox kind, OS and architecture, or the deployed host) and a **link to the
evidence** (a workflow run, a PR on the test repository, a log or screenshot in the issue tracker).
Keep cloud and local evidence apart, and a scripted-model run apart from a paid one.

Use a disposable repository (the existing `kunemi-group/dotrix-test` or a new one) and throwaway keys
where you can. Never paste a real key, token or secret value into the evidence.

Environments, from cheapest to most expensive:

| Kind | What it needs |
| --- | --- |
| **Live model** | A real provider key; Postgres and Redis locally or in the Live models workflow |
| **Real sandbox** | A Docker Cloud account (`DOTRIX_DOCKER_CLOUD_ID`, `DOTRIX_DOCKER_CLOUD_PAT`, a published `DOTRIX_CODING_IMAGE`) or an OpenShell gateway (`openshell` CLI with a gateway selected, the coding image, the provider profiles imported; [infra/coding/README.md](../infra/coding/README.md)) |
| **Real machine** | The OS and architecture named, the engine binaries installed, a linked checkout |
| **Packaged app** | The Windows installer from a release, installed on a real machine |
| **Production** | The deployed host with the real GitHub App, email and a disposable repository |

## Tests that run against real things

These already exist. They skip unless given what they need.

| Test | Covers | Run it |
| --- | --- | --- |
| [`test_live_chat.py`](../apps/backend/tests/integration/test_live_chat.py) | Nova on DeepAgents and fx, per provider: knowledge read and follow-up, a Build change through approval, a general question answered without reading, the activity line | `DOTRIX_LIVE_<PROVIDER>_API_KEY` (ANTHROPIC, OPENAI, NVIDIA); fx tests also need the optional fx host. `uv run pytest apps/backend/tests/integration/test_live_chat.py` |
| [`test_live_coding.py`](../apps/backend/tests/integration/test_live_coding.py) | Kai on Claude Code, Codex, OpenCode and fx: issue to PR in a real sandbox, skills following the change, an unclear issue never reaching main, a pinned skill resource, NVIDIA bug fix with the browser | A provider key plus `DOTRIX_LIVE_CODING_SANDBOX=docker-cloud` (with the Docker Cloud settings and `DOTRIX_LIVE_CODING_IMAGE`) or `openshell`. Paid |
| [`test_live_scripts.py`](../apps/backend/tests/integration/test_live_scripts.py) | Code Mode on real models, with and without `run_script`; the opt-in benchmark | A provider key; `DOTRIX_LIVE_SCRIPT_BENCHMARK=1` for the benchmark ([Code Mode benchmark](code-mode-benchmark.md)) |
| [Live models workflow](../.github/workflows/live.yml) | The two live suites above on a picked provider, Kai in Docker Cloud | Actions → Live models → Run workflow (provider, suite). Keys and Docker Cloud secrets live in the `live-models` environment |
| [`test_opencode_browser.py`](../apps/backend/tests/unit/test_opencode_browser.py) | The pinned OpenCode and Playwright MCP against a scripted model and a real local page | `DOTRIX_TEST_OPENCODE`, `DOTRIX_TEST_PLAYWRIGHT_MCP`, `DOTRIX_TEST_CHROMIUM` (or on PATH). No paid calls |
| [`test_real_local_engines.py`](../apps/cli/tests/test_real_local_engines.py) | Real Claude Code, Codex and fx binaries in the native runner, with scripted models and the desktop's MCP transport | `DOTRIX_TEST_CODEX`, `DOTRIX_TEST_FX` and the Claude Code binary. No paid calls |
| [`handoff.test.mjs`](../packages/engine/src/dotrix_engine/runtimes/fx_host/handoff.test.mjs) | libfx engine handoff and resume with an in-memory journal | `node --test` on the file, with the fx host installed |
| [Rollback runbook](runbooks/kai-runtime-rollback.md) | Routing new work back to the earlier defaults and recovering active runs | By hand on the deployed host |

## Kai runtime by default

Roadmap: [Kai by default](product.md#1-before-the-beta). Needed before the beta.

- [ ] **fx chat on paid models.** `test_live_chat.py` passes for fx on Anthropic and OpenAI (live model). It has passed on NVIDIA (2026-11-21) only.
- [ ] **fx coding on paid models.** `test_live_coding.py` passes for fx on Anthropic and OpenAI in Docker Cloud (real sandbox). This is also the first fx turn through the platform's own sandbox.
- [ ] **Google on fx chat.** Either a live pass on Google with the kai.2 runtime, or keep Google listed as unsupported for fx.
- [ ] **Comparison against the earlier defaults.** Set the acceptance thresholds first, then run fixed tasks on fx and on DeepAgents, Claude Code, Codex and OpenCode. Record task success, latency, cost, recovery and how often a person stepped in.
- [ ] **The full journey on fx** (production): Nova → Kai → Juno, with a denied action, a Stop, a worker restart, and a pending approval kept across that restart.
- [ ] **Rollback rehearsal** (production): `DOTRIX_CHAT_DEFAULT_RUNTIME=deepagents` and `DOTRIX_CODING_AGENT=legacy` route new work back. Active runs drain or recover on their recorded runtime, per the [runbook](runbooks/kai-runtime-rollback.md).

## Cloud sandboxes

### Docker Cloud (staging and production)

Tested so far only against a fake of its API (`tests/unit/test_docker_cloud.py`).

- [ ] **Start and isolation.** `DOTRIX_CODING_SANDBOX=docker-cloud` with the account, token and a published image; the API and worker start. One authorised turn on a disposable repository has a network policy that allows only the model API host and the session's hosts. A request to another host from inside the sandbox is refused and appears in the turn's blocked-host report. The model key is never in the sandbox's environment: `env` shows only the placeholder.
- [ ] **Network policy entries.** Exact hosts, `*.domain` and `host:port` entries each reach what they allow and nothing more.
- [ ] **Stop and recovery.** Stop ends a running turn within seconds and leaves no sandbox running. A worker killed mid-turn leaves the run `recovery_required`, and Recover settles it from GitHub.
- [ ] **Sleep and wake.** The sandbox sleeps between turns and wakes for the next with its files. It is deleted after `DOTRIX_CODING_SLEEP_DAYS`, beyond `DOTRIX_CODING_SLEEP_MAX` per workspace, and at once by "Delete sandbox". The 10-minute sweep removes stopped sandboxes and secrets nothing references.
- [ ] **Cloud checkout recovery.** A Build turn whose sandbox is lost mid-turn restores its last checkpoint in a fresh sandbox, then is verified and published as usual.
- [ ] **Host secrets.** A project secret for a host other than the model API, as a custom secret with injection, reaches that host with the real value in its header. `echo $NAME` inside the sandbox shows only the placeholder. Repeat with a `host:port` entry.
- [ ] **Workspace secrets.** A project referencing a workspace secret gets it. Rotating its value reaches that project's next turn.
- [ ] **Setup-only secrets.** The setup script can use one. After `drop_secrets` deletes it, a request from Kai's commands to that host no longer carries the value. Check whether injection stops as soon as the secret is deleted.
- [ ] **Waking with a deleted secret.** A sandbox whose stored secrets include a deleted (setup-only) one still wakes for the next turn.
- [ ] **Custom images.** An operator-approved image pinned by digest is used for the session and kept by its follow-ups.
- [ ] **Plan mode's Landlock boundary.** A Plan turn starts inside the deployed coding image: only scratch storage is writable, and every paid engine runs under it.

### OpenShell (development)

The policy and profiles follow OpenShell's schema reference (v0.1.10) and haven't run on a gateway. A
new Claude Code session has `.claude/settings.json` rules for the `openshell` CLI. Once these pass,
remove the broad `docker run *` rule from that file.

- [ ] **Provider profiles.** Each `infra/coding/dotrix-*.yaml` lints and imports (`openshell provider profile lint -f`, then `import`), and a turn on each engine reaches its model through its provider.
- [ ] **Project hosts.** The policy's `tls: skip` endpoints, `**.domain` wildcards and the `/**` binary rule let any program reach the session's hosts and nothing else.
- [ ] **Host secrets.** The per-turn secret profile imports. `auth_style: bearer` and `auth_style: header` with `header_name` each put the real value in the header. An inspected endpoint (`protocol: rest`) for a secret's host works beside relayed `**.domain` endpoints, including one that covers it.
- [ ] **Setup-only secrets.** `openshell sandbox provider detach <sandbox> <provider>` is the right command and takes effect for processes started afterwards. If the command is different, fix `OpenShellSession.drop_secrets`. Until then every turn with a setup-only secret stops safely before Kai runs. Also confirm the expected limitation: the secret's host is unreachable after setup.
- [ ] **Clean-up.** Closing a sandbox deletes the sandbox, its providers and its per-turn profiles; nothing is left in `openshell provider list`.

## Cloud coding engines and providers

Each row is `test_live_coding.py` in a real sandbox with that provider's key, plus the browser where
noted. Earlier evidence is for older pins or for Docker containers on the worker, which have been removed;
re-run on the current pins in Docker Cloud.

- [ ] **Claude Code 2.1.323** on Anthropic.
- [ ] **Codex 0.169.0** on OpenAI. 0.166.0 has run on GPT-5.5 (2026-10-31).
- [ ] **OpenCode 2.3.0** on Anthropic, OpenAI and Google. xAI, DeepSeek, Mistral, Groq, OpenRouter and NVIDIA have passed against fake APIs only.
- [ ] **fx `0.0.18-kai.2`** on OpenAI, Anthropic and NVIDIA. NVIDIA fixed a bug in the image earlier; the current pin hasn't been rebuilt or deployed.
- [ ] **NVIDIA coding with the browser** for OpenCode and fx in the cloud (`test_live_nvidia_bug_and_browser`).
- [ ] **The cloud browser** on each engine with a real model: the Playwright MCP server starts, the model uses it, and screenshots are kept per turn.
- [ ] **Steering and background tasks** on a real fx cloud turn: a steer is delivered mid-turn, a background command keeps running between turns, and the reaper records its end.
- [ ] **Parallel builds.** Keep `DOTRIX_CODING_PARALLEL` off until the paid engines pass under the read-only Plan wrapper, crash, recovery and cancellation hold under load, and Docker Cloud and OpenShell are compatible.

## Chat

- [ ] **fx changes and approvals on real models.** Approve, reject, Accept edits and Plan, each with a paid model (today they're tested on the real libfx host with a fake model).
- [ ] **Distributed failure.** Kill workers mid-turn under load, on both runtimes. Turns resume once, ask before any change, and no change goes through twice.
- [ ] **Durable delegation on a live provider.** Nova delegates to specialists by name, including two read-only specialists at once, on both runtimes.
- [ ] **Steering on a real model.** A steer changes the reply, and a queued follow-up runs after the turn.
- [ ] **Code Mode adoption and savings.** Run the [Code Mode benchmark](code-mode-benchmark.md) with repeats before claiming that scripts save calls or tokens.
- [ ] **Automatic model routing.** With `automatic_model_routing` on, measure quality and cost on real conversations before choosing defaults. Missing usage data can't support a savings claim.
- [ ] **Repository knowledge.** Evaluate the discovery run ("Explain the repository") on a real model and a real repository: are claims cited, and are the gaps named?

## Local coding on real machines

Each row needs the OS and architecture named, the pinned engine, a linked checkout and the person's own
key. Linux namespace paths have real-binary tests with scripted models; everything else is implemented
but unchecked.

- [ ] **Linux, in the desktop app.** The Claude Code (2.1.296) and fx namespace paths in the actual Electron app: commands, the Browser pane, Stop.
- [ ] **Linux, paid models.** One native Claude Code turn and one native fx turn with real keys.
- [ ] **macOS arm64.** The Seatbelt (`sandbox-exec`) boundary for Claude Code and fx with the bundled fx: commands inside the worktree work, writes outside are refused, direct networking is blocked. Codex's native workspace-write sandbox runs.
- [ ] **Windows x64.** The AppContainer and Job Object boundary for Claude Code. fx in WSL 2 Bubblewrap, including the install guidance when WSL 2, Bubblewrap or fx is missing. Codex's native sandbox. Stop reaching the whole process tree.
- [ ] **Docker Sandboxes (`sbx`).** A real `sbx` on a compatible host (KVM, Hyper-V or Apple's hypervisor): templates, sign-in through `sbx secret`, cancellation, and the network policy. Note that the guest can't reach the desktop's Browser server.
- [ ] **OpenCode's local shell.** Either an enforced native boundary, or `sbx` validated on each host it supports. Never lift the `bash` denial without one.
- [ ] **OAuth and subscription sign-ins.** A safe relay for Claude Code and fx credentials, which isn't implemented yet. Today these fall back to file-only turns.
- [ ] **The desktop Browser pane.** A person's tabs, Kai's tab on a local turn, Settings → Browser, `app_start` and `app_logs` with a real model.
- [ ] **Local network allowlist.** `DOTRIX_CODING_NETWORK_ALLOW` only narrows the session's policy, checked on a host where outbound access is otherwise open. Native fx's `web_fetch` refusal is still unverified on an externally reachable host.
- [ ] **Worktree recovery.** `dotrix worktree snapshot`, `restore` and `cleanup` on a real interrupted local turn.

## Desktop app and releases

- [ ] **Windows installer, end to end.** Install from a release on a real machine: device sign-in, pick a folder, the runner links, a local turn codes, the update bar installs the next release, and What's new shows it.
- [ ] **Signing.** A signed Windows build, so SmartScreen no longer warns.
- [ ] **Release flow.** Merging stage into main publishes only new component versions (`vX.Y.Z` desktop, `cli-vX.Y.Z`, `platform-vX.Y.Z`), and the Unreleased notes become a version.
- [ ] **Coding image.** The coding-image workflow publishes the image with its immutable commit tag, and the deployed worker runs it.
- [ ] **macOS and Linux packaging**, updates and notarization (after the beta).

## Readiness checks

What the beta needs on the deployed host. **Local** means a developer machine or CI with synthetic
GitHub and models. **Production** means the deployed host with the real GitHub App and a real model key,
on a disposable repository.

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
- [ ] Resources: the admin console's Resources page lists every API replica and worker of the deployment with memory, CPU and start time, and a stopped worker drops off within 90 seconds. Compare its figures with the [measured footprint](../deploy/README.md#measured-footprint-2026-11-28) to size the host.

### Sandbox isolation (production)

The Docker Cloud checks under [Cloud sandboxes](#docker-cloud-staging-and-production): start and
isolation, Stop and recovery, sleep and wake.

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
- [ ] GitHub Issues import from a real repository: preview, select, import once, and a retry imports nothing twice.

### The core loop (production, one disposable repository)

- [ ] Discuss → Plan → Build in one conversation: Nova delegates to a specialist by name (Lyra, Orion, Vega, Juno, Echo), the plan is saved, "Build this plan" creates Kai's approval notification, approving it in the Inbox starts Kai.
- [ ] Kai's turn: steps and command output visible in Code, the diff per file, the branch pushed, the PR opened by the App, the commit's checks shown for that exact commit.
- [ ] Juno's review posted on the PR as a comment (never an approval), its findings on their diff lines in Code.
- [ ] The outcome returns to the originating conversation (Nova's summary names the PR and the review); a different conversation cannot read it.
- [ ] A failing CI run on the PR starts Juno's triage once, shown on the PR and in Code with "Ask Kai to fix".
- [ ] Stop mid-turn, a rejected approval, and a turn whose worker was killed each show their true state; no success or PR is invented.
- [ ] Steering a running Nova turn: the steer is accepted and changes the reply; a queued follow-up runs after the turn.
- [ ] A merge is done by the person on GitHub; the task stays open until they close it.
- [ ] The delivered journeys J01–J08 each once, with live GitHub and model evidence recorded apart from the synthetic tests.

### Failure handling and limits (local, then production)

- [ ] Model limit mid-reply: the run stops, says so, and Continue resumes from the checkpoint (local: scripted model; production: a real 429).
- [ ] The worker restarted mid-chat-run: the run resumes within about two minutes under a new attempt, asks before any change, and tool calls the cut-off attempt left are not repeated.
- [ ] A coding run's lease lapses: `recovery_required` within about two minutes; Recover adopts the PR when the push landed.
- [ ] Usage: each run's tokens and cost shown; Codex and fx priced from their tokens; a run with missing usage marked incomplete rather than free.

### Support paths

- [x] A way to report a problem from the app: Help & resources → Report a problem opens a new issue on the repository (public), 2026-11-09.
- [ ] The CHANGELOG's Unreleased section turned into a version before the beta, and What's new showing it in the desktop app. The 0.2.0 version bump is recorded on stage; verify the release workflow/tag on main and What's new in an installed app before marking this complete.
- [x] A short "Getting started" for beta participants: the supported configuration, connecting a key and GitHub, what Manual approval means, how to stop a run, and how to report a problem. On the public site at [dotrix.cc/#start](https://dotrix.cc/#start), linked from the app's Help & resources → Getting started, and in full at [Getting started](product.md#getting-started), 2026-11-12.
