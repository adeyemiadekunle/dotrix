# The image coding runs use in OpenShell (DOTRIX_CODING_IMAGE): Claude Code, Codex, OpenCode, fx, git, and
# common toolchains so the agent can run a project's tests. Add what your projects need.
#
#   docker build -t dotrix-coding:latest infra/coding
#
# No credentials are baked in: the model key is attached per run as an OpenShell provider, and
# the agent never gets a GitHub token (the worker clones and pushes outside the sandbox).
# The full Debian image already has git, curl, Python 3, and a C toolchain.
FROM node:22-bookworm

# The CLIs, installed globally; their binaries are what the provider profiles allow to reach
# the model APIs (see dotrix-claude-code.yaml and dotrix-codex.yaml). Pinned like OpenCode and fx, because
# modules/coding/tools.py reads their headless events and passes their flags: Claude Code as checked on a
# real model (2.1.296, docs/coding-agent.md Phase 0); Codex at the release its flags were checked against
# (0.166.0: `exec --json --skip-git-repo-check --sandbox danger-full-access --ephemeral`; not yet run on a model).
# Raise a version only after checking its events and flags.
ARG CLAUDE_CODE_VERSION=2.1.296
ARG CODEX_VERSION=0.166.0
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} @openai/codex@${CODEX_VERSION} \
  && claude --version && codex --version

# OpenCode 2 (DOTRIX_CODING_AGENT=opencode): any provider's model. Pinned, because its headless events
# and session export are what modules/coding/tools.py reads (checked on 2.1.4); its profiles are
# dotrix-opencode-*.yaml.
ARG OPENCODE_VERSION=2.1.4
RUN npm install -g @opencode/cli@${OPENCODE_VERSION} && opencode --version

# fx (DOTRIX_CODING_FX=true): Kai on an OpenAI-compatible provider, driven over ACP by fx-acp.mjs. Pinned,
# because the driver reads its ACP messages and modes (written against 0.0.16's source); the release is
# fx's own (releases.fx.sh, what `fx upgrade` fetches), checked against its published SHA-256. Its profiles
# are dotrix-fx-*.yaml. Needs releases.fx.sh reachable where the image is built, never in the sandbox.
ARG FX_VERSION=0.0.16
RUN set -eu; \
  case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "fx: unsupported $(uname -m)"; exit 1 ;; esac; \
  base="https://releases.fx.sh/v${FX_VERSION}/fx-linux-${arch}.tar.gz"; \
  cd /tmp && curl -fsSL -o fx.tar.gz "$base" && curl -fsSL -o fx.tar.gz.sha256 "$base.sha256"; \
  echo "$(cut -d' ' -f1 fx.tar.gz.sha256)  fx.tar.gz" | sha256sum -c -; \
  mkdir fx && tar -xzf fx.tar.gz -C fx && install -m 0755 "$(find fx -type f -name fx | head -n1)" /usr/local/bin/fx; \
  rm -rf fx fx.tar.gz fx.tar.gz.sha256; \
  fx --version
COPY fx-acp.mjs /opt/dotrix/fx-acp.mjs

# A browser for the agent (the platform passes it as an MCP server, `playwright-mcp`): Playwright's
# Chromium, headless, in a shared folder the unprivileged user can run. It opens the app the agent
# serves on localhost inside the sandbox; the sandbox's network rules still apply to everything else.
ARG PLAYWRIGHT_MCP_VERSION=0.0.83
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npm install -g @playwright/mcp@${PLAYWRIGHT_MCP_VERSION} \
  && cd "$(npm root -g)/@playwright/mcp" && npx --no-install playwright install --with-deps chromium \
  && chmod -R a+rX /opt/ms-playwright && playwright-mcp --version

# The Docker sandbox's way out (DOTRIX_CODING_SANDBOX=docker): run from this image in a container
# of its own, it lets the agent reach the model API and nothing else.
COPY egress-proxy.mjs /opt/dotrix/egress-proxy.mjs

# OpenShell drops the agent to this user (policy: run_as_user/run_as_group "sandbox").
RUN groupadd --gid 1500 sandbox && useradd --uid 1500 --gid sandbox --home-dir /sandbox --create-home sandbox
WORKDIR /sandbox
USER sandbox

# The sandbox supervisor replaces CMD; coding runs start `sleep infinity` and exec the agent.
CMD ["sleep", "infinity"]
