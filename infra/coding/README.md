# Coding runs: sandbox setup

"Start coding" on an issue runs Claude Code (or Codex) on a copy of the project's repo in a
sandbox. The worker then pushes a new branch and opens a PR through the dotrix GitHub App. This
folder holds what the sandbox needs: the image, and the OpenShell provider profiles for the model
keys.

## How a run is contained

- **No GitHub token in the sandbox.** The worker fetches the repo with an installation token
  scoped to that one repo, then gives the agent the tracked files and a fresh git history of
  their own, with no remote. Afterwards it reads the agent's changes back as a patch and checks
  them: nothing under `.dotrix/`, `.github/workflows/`, or `.git`. Only then does it commit,
  push a new branch (`dotrix/<key>-<title>-<id>`, never the default branch, never forced), and
  open the PR. Merging is a person's job.
- **Network.** The policy (`sandbox_policy()` in
  `apps/backend/src/dotrix_backend/modules/coding/sandbox.py`) adds no network rules of its
  own. The provider attached to each run allows the model API only (api.anthropic.com or
  api.openai.com), and only for the coding tool's binaries. Everything else is blocked,
  including GitHub and package registries. To let the agent install dependencies, add rules for
  your registries to that policy.
- **Filesystem.** The sandbox's working directory, which holds the repo, is writable, and so is
  `/tmp`. The system is read-only (Landlock, `hard_requirement`). The agent runs as an
  unprivileged user.
- **Credentials.** The model key becomes an OpenShell provider for the length of the run.
  OpenShell keeps the key and gives the sandbox a placeholder, which its proxy swaps for the key
  only on requests to the model API. The key never sits in the sandbox's filesystem.
- **Limits.** Each run stops at `DOTRIX_CODING_TIMEOUT_MINUTES` (30 by default), at
  `DOTRIX_CODING_TOKEN_BUDGET` tokens, or when someone presses Stop. The sandbox is deleted
  when the run ends, however it ends.
- **Guarding the default branch.** The worker never pushes to the default branch. GitHub can
  enforce that as well: add a ruleset or branch protection to the default branch (require a pull
  request with one approval). The app's token can't add workflows, because the app has no
  Workflows permission.

## Set up Docker (the simplest: once per machine that runs agents)

1. Docker running (Docker Desktop on Windows and macOS).
2. Build the image: `docker build -t dotrix-coding:latest infra/coding`
3. Add these to `.env` on the machine that runs agents (the worker, or the API in local mode):
   ```shell
   DOTRIX_CODING_SANDBOX=docker
   DOTRIX_CODING_IMAGE=dotrix-coding:latest
   ANTHROPIC_API_KEY=...   # Claude Code; with only OPENAI_API_KEY, Codex codes instead
   ```

Each run gets:
- **A network with no route out** (`docker network create --internal`), and on it the agent's
  container and an **egress proxy** (`egress-proxy.mjs`, from the same image, also on the default
  network). The agent's `HTTPS_PROXY` points at it; it tunnels to the tool's model API
  (api.anthropic.com or api.openai.com, or the host of `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`)
  and refuses everything else, GitHub and package registries included.
- **The agent's container:** a read-only system, `/tmp` and the repo's volume writable, all
  capabilities dropped, `no-new-privileges`, the image's `sandbox` user (uid 1500), 4 GB of
  memory, 2 CPUs, 512 processes. The repo is copied in as a tar extracted by that user.
- **Cleanup:** both containers, the volume, and the network are removed when the run ends,
  however it ends. Each carries the label `dotrix.run=<run id>`
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
2. Build the image, which installs Claude Code, Codex, and git:
   `docker build -t dotrix-coding:latest infra/coding`
3. Import the provider profiles:
   ```shell
   openshell provider profile import -f infra/coding/dotrix-claude-code.yaml --global
   openshell provider profile import -f infra/coding/dotrix-codex.yaml --global
   ```
4. Add these to `.env` on the machine that runs agents: the worker, or the API in local mode.
   ```shell
   DOTRIX_CODING_SANDBOX=openshell
   DOTRIX_CODING_IMAGE=dotrix-coding:latest
   ANTHROPIC_API_KEY=...   # Claude Code; with only OPENAI_API_KEY, Codex codes instead
   ```
   You also need the GitHub App, with Contents (write) and Pull requests (write); see CLAUDE.md
   step 5.

For development without OpenShell, `DOTRIX_CODING_SANDBOX=local` runs the agent in a
temporary folder on your machine. **It has no isolation**, and production refuses to start with
it.

## Check a sandbox by hand

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
