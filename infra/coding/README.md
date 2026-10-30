# Coding runs: sandbox setup

Kai, the coding agent, works on an issue in a sandbox: from "Start coding" on the issue, Build
mode in Chat, or a session in Chat's Code tab. Underneath, Kai is one of three headless tools,
each behind `CodingTool` (`apps/backend/src/dotrix_backend/modules/coding/tools.py`):

| Tool | Runs on | Chosen by |
| --- | --- | --- |
| Claude Code | Anthropic | Your default or session choice; Auto when Anthropic is available without OpenAI |
| Codex | OpenAI | Your default or session choice; Auto when OpenAI is available |
| OpenCode 2 (pinned in the image) | Anthropic, OpenAI, Google, xAI/Grok, DeepSeek, Mistral, Groq, OpenRouter | Your default or session choice; Auto with another provider |

Account → Your models saves a personal default. A new session can override it; follow-up turns
keep their recorded tool and model. Unavailable defaults fall back to a compatible tool. OpenCode
uses an available model from the platform catalogue; its session picker can choose another.
Every person brings their own provider key. The web app requires a usable personal key before
continuing in a real workspace (the seeded demo stays public). Shared workspace and server model keys
are not supported. Scheduled runs use the creator's own key.

The worker gives the tool a copy of the repo and a brief, reads its changes back, then pushes a
new branch and opens a PR through the dotrix GitHub App. This folder holds what the sandbox
needs: the image (all three tools, git, Playwright MCP for the agent's own browser, and the
egress proxy) and the OpenShell provider profiles for the model keys.

## A run, from start to PR

1. **Approval.** In Manual a run waits for an approver. In Accept edits and Auto it starts at
   once, approved by whoever asked (the workspace's cap and the person's own rights apply, as in
   chat).
2. **Keys.** Only the requesting person's own key pays for a run. Scheduled runs use the
   creator's personal key. No server, workspace, dotrix, or approver credential stands in.
3. **The brief.** The issue and its acceptance criteria, its epic and what it waits on, the
   documents it links to in the project graph, and the repository's wiki pages that bear on it
   (`coding/brief.py`). Issue and document text is wrapped as data, never instructions.
4. **The sandbox.** The worker fetches the repo with an installation token scoped to that one
   repo, then gives the agent the tracked files and a fresh git history with no remote.
5. **The turn.** The tool works headless. Its events stream into the session (`coding_events`),
   and Stop signals it inside the sandbox (SIGINT, then SIGKILL after 5 seconds).
6. **The changes.** The worker reads them back as a patch and checks them (`coding/guard.py`).
   It refuses anything under `.dotrix/` or `.git`, and CI configuration: all of `.github/`,
   other CI systems' folders (`.circleci`, `.gitlab`, `.buildkite`, …) and root files
   (`.gitlab-ci.yml`, `Jenkinsfile`, …). Files CI runs without being CI configuration (build
   scripts, test setup) are named on the PR for a person to review first.
7. **The push.** A new branch (`dotrix/<key>-<title>-<id>`, never the default branch, never
   forced), then the PR. The issue moves to review and the Reviewer reads the PR. A person
   merges.

**Sessions.** A session keeps its sandbox warm between turns (`DOTRIX_CODING_WARM_MAX` per
workspace, closed after `DOTRIX_CODING_IDLE_MINUTES`). Claude Code's transcript and OpenCode's
session export are saved, encrypted, and restored into a fresh sandbox, so a follow-up resumes
where the last turn stopped, on the same branch and PR (it needs storage and
`DOTRIX_ENCRYPTION_KEY`; without them a new sandbox starts the tool afresh). The agent's browser steps and
screenshots are kept per turn.

**Leases and recovery.** The worker holds a run's lease while it works
(`DOTRIX_CODING_LEASE_SECONDS`, renewed every third of it); a newer attempt fences an older one
off. A run whose worker stopped, or whose push or PR response was lost, becomes
`recovery_required` and is settled from what GitHub shows (`coding/recovery.py`):
- its PR is adopted, or opened, when the branch is at the recorded commit;
- the turn runs again, twice in all, when nothing was published;
- anything else waits for Recover in the Code tab.

## How a run is contained

- **No GitHub token in the sandbox.** See the steps above: the agent never has a remote, and
  only the worker pushes, after the guard.
- **Branches live on a fork.** With `DOTRIX_CODING_FORK_OWNER` set (required in staging and
  production), the app forks each repo into that organisation (`<owner>-<repo>`), pushes the
  branch there, and opens the PR from the fork. GitHub gives a fork's PR no secrets, so the
  agent's code can't reach them through CI, and the repo's own token only reads and opens the
  PR. Setup:
  1. A GitHub organisation for the forks (e.g. `dotrix-fork`), with the dotrix GitHub App
     installed on it, with Administration (write) and Contents (write).
  2. For private repos: the repo's organisation allows forking private repositories
     (Settings → Member privileges → Repository forking), and the repo does too.
  3. On each repo (or its organisation), under Settings → Actions → General: keep "Send secrets
     to workflows from fork pull requests" off. Set "Require approval for fork pull request
     workflows" to all outside collaborators, so a person approves before checks run.
- **Network.** The only host a run reaches is its tool's model API. That is api.anthropic.com,
  api.openai.com, or generativelanguage.googleapis.com, or the host of `ANTHROPIC_BASE_URL`,
  `OPENAI_BASE_URL` or `GOOGLE_GEMINI_BASE_URL`. GitHub, package registries, and everything else
  are blocked. To let the agent install dependencies, add your registries to the Docker egress
  allowlist and OpenShell's policy (`sandbox_policy()` in `coding/sandbox.py`).
- **OpenCode's own settings are ours.** Its config comes from `OPENCODE_CONFIG_CONTENT` (that
  provider only; `webfetch`, `websearch` and `question` denied). A repo's `opencode.json` never
  loads (`OPENCODE_DISABLE_PROJECT_CONFIG`), and no model list is fetched.
- **fx (opt-in) runs in its full-access mode, with settings we write.** `fx-acp.mjs` writes
  `~/.fx/settings.json` each turn (one OpenAI-compatible provider, its key read from the provider's
  variable by name, auto-upgrade off) and drives `fx acp`; the sandbox, not fx, is the boundary, and
  nobody is there to answer fx's permission prompts. fx's web tools reach nothing (the sandbox blocks
  them). People only ever see Kai: no step, failure, commit message or PR names the engine. Which engine ran is on the run, in the audit log, and in the worker's log; people pick one only in the new-session form and Account → Your models.
- **Filesystem.** The repo and `/tmp` are writable; the system is read-only. The agent runs as
  the image's unprivileged `sandbox` user (uid 1500).
- **Limits.** Personal BYOK has no platform token-budget setting or coding token-cap enforcement.
  Each coding turn still stops at `DOTRIX_CODING_TIMEOUT_MINUTES`
  (30 by default) or Stop. Each cloud worker runs two turns at once (`DOTRIX_CODING_MAX_RUNS=2`);
  the rest wait for a free sandbox. Idle cached sandboxes have a separate per-workspace limit
  (`DOTRIX_CODING_WARM_MAX`) and timeout. They have no coding turn executing but remain running
  Docker containers and can retain memory and background processes. The active-turn limit is per
  worker process: this deployment uses one cloud worker; adding workers multiplies capacity.
- **Guarding the default branch.** The worker never pushes to the default branch. GitHub can
  enforce that as well: add a ruleset or branch protection to the default branch (require a pull
  request with one approval). The app's token can't add workflows, because the app has no
  Workflows permission.

## Settings

| Setting | Default | What |
| --- | --- | --- |
| `DOTRIX_CODING_SANDBOX` | `off` outside Compose; `docker` in Compose | `docker`, `openshell`, or `local` (development only: no isolation; production refuses it) |
| `DOTRIX_CODING_IMAGE` | `dotrix-coding:latest` | The image built from this folder |
| `DOTRIX_CODING_AGENT` | `auto` | `claude-code`, `codex`, `opencode`, or `fx` |
| `DOTRIX_CODING_CLAUDE_MODEL`, `DOTRIX_CODING_CODEX_MODEL` | the tool's default | A model for Claude Code or Codex |
| `DOTRIX_CODING_OPENCODE_MODEL` | first available catalogue model | Optional server default, e.g. `xai:grok-4.7` |
| `DOTRIX_CODING_FX` | `false` | Offer fx as Kai's engine. Off: fx is never offered or chosen. On: only for someone who picks it (or `DOTRIX_CODING_AGENT=fx`) |
| `DOTRIX_CODING_FX_MODEL` | first available model | fx's default, on an OpenAI-compatible provider: OpenAI, xAI, DeepSeek, Mistral, Groq, OpenRouter (not Anthropic or Google yet) |
| `DOTRIX_CODING_FX_DRIVER` | `/opt/dotrix/fx-acp.mjs` | Where the image puts the ACP driver |
| `DOTRIX_CODING_TIMEOUT_MINUTES` | 30 | Per turn |
| `DOTRIX_CODING_LEASE_SECONDS` | 120 | A lapsed lease means recovery, found within about this long |
| `DOTRIX_CODING_WARM_MAX`, `DOTRIX_CODING_IDLE_MINUTES` | 3, 30 | Warm sandboxes kept per workspace, and for how long idle (0: every turn starts fresh and resumes from the saved session) |
| `DOTRIX_CODING_MAX_RUNS` | 2 | Runs working at once per worker (0: no limit) |
| `DOTRIX_CODING_MEMORY`, `DOTRIX_CODING_CPUS` | `4g`, 2 | Each Docker sandbox |
| `DOTRIX_CODING_DOCKER_RUNTIME` | Docker's | `runsc` for gVisor |
| `DOTRIX_CODING_FORK_OWNER` | none | The organisation branches are pushed to as a fork (required in staging and production) |

You also need the GitHub App, with Contents (write) and Pull requests (write).

## Set up Docker (the simplest: once per machine that runs agents)

1. Docker running (Docker Desktop on Windows and macOS).
2. Build the image: `docker build -t dotrix-coding:latest infra/coding`
3. Add these to `.env` on the machine that runs agents (the worker, or the API in local mode):
   ```shell
   DOTRIX_CODING_SANDBOX=docker
   DOTRIX_CODING_IMAGE=dotrix-coding:latest
   ```
   For OpenCode instead, on any provider's model (the key is that provider's):
   ```shell
   DOTRIX_CODING_AGENT=opencode
   DOTRIX_CODING_OPENCODE_MODEL=anthropic:claude-sonnet-5-5   # or openai:…, google_genai:…
   ```
   Sign in and connect your own provider key in Account → Your models before starting a run.
   Model API keys are not configured in the platform environment.

Each run gets:
- **A network with no route out** (`docker network create --internal`), and on it the agent's
  container and an **egress proxy** (`egress-proxy.mjs`, from the same image, also on the default
  network). The agent's `HTTPS_PROXY` points at it; it tunnels to the tool's model API only
  (above) and refuses everything else.
- **The agent's container:** a read-only system, `/tmp` and the repo's volume writable, all
  capabilities dropped, `no-new-privileges`, the `sandbox` user, `DOTRIX_CODING_MEMORY` and
  `DOTRIX_CODING_CPUS`, 512 processes. The repo is copied in as a tar extracted by that user.
- **Cleanup:** both containers, the volume, and the network are removed when the run (or, for a
  warm session, the session) ends, however it ends. Each carries the label `dotrix.run=<run id>`
  (`docker ps -a --filter label=dotrix.run` finds any a crash left behind).

Compared with OpenShell, the model key is in the agent's environment rather than swapped in by
a proxy, and the proxy allows the model API to any process in the container, not only the
tool's binary. The key can still only reach the model API. `tests/unit/test_coding_docker.py`
checks all of this against a real container (it's skipped where the image isn't built).

## Set up OpenShell (once per machine that runs agents)

1. Install OpenShell and start a gateway. See
   [Installation](https://docs.nvidia.com/openshell/latest/about/installation). For local
   development the gateway runs on Docker; production needs a host or cluster. OpenShell is
   young: test its isolation between tenants before you run other people's code on it.
   The machine that runs agents also needs the `openshell` CLI, selected to that gateway, and
   an `ssh` client: uploads to a sandbox go over SSH.
2. Build the image, which installs Claude Code, Codex, OpenCode, fx, and git, each at a pinned version
   (`CLAUDE_CODE_VERSION`, `CODEX_VERSION`, `OPENCODE_VERSION`, `FX_VERSION`; fx from releases.fx.sh,
   checked against its SHA-256). Raise one with `--build-arg` only after checking its events and flags:
   `docker build -t dotrix-coding:latest infra/coding`
3. Import the provider profiles:
   ```shell
   openshell provider profile import -f infra/coding/dotrix-claude-code.yaml --global
   openshell provider profile import -f infra/coding/dotrix-codex.yaml --global
   # OpenCode, one per provider it may run on (not yet checked on a gateway):
   openshell provider profile import -f infra/coding/dotrix-opencode-anthropic.yaml --global
   openshell provider profile import -f infra/coding/dotrix-opencode-openai.yaml --global
   openshell provider profile import -f infra/coding/dotrix-opencode-google.yaml --global
   # fx, one per provider it may run on (DOTRIX_CODING_FX=true; not yet checked on a gateway):
   for p in openai xai deepseek mistral groq openrouter; do
     openshell provider profile import -f "infra/coding/dotrix-fx-$p.yaml" --global
   done
   ```
4. Add these to `.env` on the machine that runs agents: the worker, or the API in local mode.
   ```shell
   DOTRIX_CODING_SANDBOX=openshell
   DOTRIX_CODING_IMAGE=dotrix-coding:latest
   ```
   Add `DOTRIX_CODING_FORK_OWNER` for the fork (above); it's required in staging and production.
   OpenShell keeps each run's key as a provider for the length of the run and gives the sandbox
   a placeholder, which its proxy swaps for the key only on requests to the model API from the
   tool's binary.

For development without OpenShell, `DOTRIX_CODING_SANDBOX=local` runs the agent in a
temporary folder on your machine. **It has no isolation**, and production refuses to start with
it.

## Status

- **Checked:** Claude Code in the Docker sandbox on a real model (a turn, resume across two
  containers, Stop, cumulative cost) and the whole flow to a PR and the Reviewer. OpenCode was
  checked against fake Anthropic and OpenAI-compatible APIs (turns, resume in a fresh sandbox,
  Stop, base URLs), and through the egress proxy to the real api.anthropic.com.
- The coding image also completed fake local API runs for xAI (Responses), DeepSeek, Mistral,
  Groq, and OpenRouter (Chat Completions), each using only its selected provider's test key.
  The real Docker isolation and Stop tests passed with this image.
- **Not yet:**
  - Paid model calls with the added providers.
  - The OpenCode profiles on an OpenShell gateway.
  - OpenCode's browser.
  - Codex (needs an OpenAI key).
  - **fx, beyond a fake.** `fx-acp.mjs` was checked against a fake `fx acp` (a turn, its steps and
    command output, resume without replay, Stop with `session/cancel`; `tests/unit/test_fx_coding.py`),
    written against fx 0.0.16's source and ACP tests. Not yet: building the image with the real fx
    release, a turn with the real binary on a fake and a paid model, its profiles on a gateway, and fx's
    browser.
  - Coding runs through Dokploy's Docker proxy (see [deploy/README.md](../../deploy/README.md)).

## Check a sandbox by hand

Use your own temporary provider key for this manual check, not a platform credential.
Run this before trusting it with a real repo. It confirms that the agent can edit, reach its
model, and nothing else.

```shell
export ANTHROPIC_API_KEY=sk-ant-...
openshell provider create --name check-claude --type dotrix-claude-code --credential ANTHROPIC_API_KEY
python -c "from dotrix_backend.modules.coding.sandbox import sandbox_policy; import json; print(json.dumps(sandbox_policy()))" > /tmp/policy.yaml
openshell sandbox create --name check --from dotrix-coding:latest --policy /tmp/policy.yaml \
  --provider check-claude --detach -- sleep infinity
mkdir -p /tmp/repo && echo 'x = 1' > /tmp/repo/a.py && git -C /tmp/repo init -q && git -C /tmp/repo add -A \
  && git -C /tmp/repo -c user.name=a -c user.email=a@b.c commit -qm base
openshell sandbox upload check /tmp/repo /sandbox --no-git-ignore

# It can edit and reach its model:
echo "Add a docstring to a.py" | openshell sandbox exec -n check --workdir /sandbox/repo --no-tty -- \
  claude -p --bare --output-format stream-json --verbose --permission-mode dontAsk --allowedTools Read,Edit,Bash
openshell sandbox exec -n check --workdir /sandbox/repo -- git diff
# And nothing more. Each of these must fail, and show as DENIED in `openshell logs check --since 5m`:
openshell sandbox exec -n check -- git clone --depth 1 https://github.com/octocat/Hello-World.git /tmp/hw
openshell sandbox exec -n check -- curl -sS https://example.com
openshell sandbox exec -n check -- touch /etc/x
openshell sandbox exec -n check -- sh -c 'env | grep -i anthropic'   # a placeholder, not the key

openshell sandbox delete check && openshell provider delete check-claude
```

What a check showed (OpenShell built from source, a local gateway on Docker, this image):
- The repo arrived in `/sandbox/repo`, owned by the `sandbox` user.
- `ANTHROPIC_API_KEY` inside the sandbox was the placeholder `openshell:resolve:env:…`, not
  the key.
- Writes to `/etc` and `/usr` were refused.
- `curl` and `git` couldn't connect anywhere, and were logged as `DENIED`.
- `curl` to api.anthropic.com was denied too: only Claude Code's binary is let through there
  (`ALLOWED …/claude-code/bin/claude.exe -> api.anthropic.com:443`).
- The agent's edits came back as a patch, and the sandbox and provider were gone afterwards.
