# syntax=docker/dockerfile:1
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
# modules/coding/tools.py reads their headless events and passes their flags. Claude Code 2.1.323 and Codex
# 0.169.0 (2026-11-13) gave the same parsed steps, output, usage and resume as the versions run on real
# models (Claude Code 2.1.296 on Claude Haiku 5.5; Codex 0.166.0 on GPT-5.5, 2026-10-31), against a scripted
# model API with Kai's own commands. Codex 0.166.0 applied a repository's own .codex/config.toml; 0.169.0
# doesn't. Raise a version only after checking its events and flags the same way.
ARG CLAUDE_CODE_VERSION=2.1.323
ARG CODEX_VERSION=0.169.0
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} @openai/codex@${CODEX_VERSION} \
  && claude --version && codex --version

# OpenCode 2 (DOTRIX_CODING_AGENT=opencode): any provider's model. Pinned, because its headless events
# and session export are what modules/coding/tools.py reads (checked on 2.1.4, and 2.3.0 against the same
# scripted model API, 2026-11-13: same steps, usage and resume); its profiles are dotrix-opencode-*.yaml.
ARG OPENCODE_VERSION=2.3.0
RUN npm install -g @opencode/cli@${OPENCODE_VERSION} && opencode --version
# ripgrep on PATH: OpenCode's glob and grep otherwise download it from GitHub at their first use, which
# the sandbox refuses, and the failed download takes the rest of the turn down with it (seen with GPT-5.5).
RUN apt-get update && apt-get install -y --no-install-recommends ripgrep && rm -rf /var/lib/apt/lists/* && rg --version

# fx (DOTRIX_CODING_FX=true): Kai on an OpenAI-compatible provider, driven over ACP by fx-acp.mjs. It is the
# Kai runtime's fx command (adeyemiadekunle/kai-runtime, fx 0.0.17 with its changes: `project_config` and
# `max_subagents`, which the driver sets, and Kai's workers' profiles listed over ACP with their `max_steps` and
# `max_tokens`, from 0.0.17-kai.2; the commands Kai leaves running named over ACP and listed by `fx/shells`, which
# fx-host.mjs reads between turns, from 0.0.17-kai.3), published to GitHub Packages as @kunemi-group/kai-cli-linux-<cpu>,
# and pinned by version and by its binary's SHA-256 (the package's fx.sha256). The install needs a GitHub token
# with read:packages as the build secret kai_packages_token; it never reaches the image or the sandbox:
#
#   docker build --secret id=kai_packages_token,env=KAI_PACKAGES_TOKEN -t dotrix-coding:latest infra/coding
#
# Its profiles are dotrix-fx-*.yaml. Needs npm.pkg.github.com reachable where the image is built, never in the sandbox.
ARG KAI_CLI_VERSION=0.0.17-kai.3
ARG KAI_CLI_SHA256_X64=6ce9b806c38a32a571895fbec10c2a256bef1531a3b7db6996f90e994e4d0287
ARG KAI_CLI_SHA256_ARM64=c85b79e3c7f31381b96fce2bc5d1a207068098c3cec4d79a52090be0c5616387
RUN --mount=type=secret,id=kai_packages_token,required=true set -eu; \
  case "$(uname -m)" in x86_64) cpu=x64; sum="$KAI_CLI_SHA256_X64" ;; aarch64|arm64) cpu=arm64; sum="$KAI_CLI_SHA256_ARM64" ;; *) echo "fx: unsupported $(uname -m)"; exit 1 ;; esac; \
  work=$(mktemp -d) && cd "$work"; \
  printf '@kunemi-group:registry=https://npm.pkg.github.com\n//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}\n' > .npmrc; \
  NODE_AUTH_TOKEN="$(cat /run/secrets/kai_packages_token)" npm pack "@kunemi-group/kai-cli-linux-${cpu}@${KAI_CLI_VERSION}" --userconfig .npmrc --ignore-scripts --silent > archive; \
  tar -xzf "$(cat archive)"; \
  echo "${sum}  package/bin/fx" | sha256sum -c -; \
  install -m 0755 package/bin/fx /usr/local/bin/fx; \
  mkdir -p /usr/local/share/doc/kai-cli && cp package/LICENSE package/THIRD_PARTY_NOTICES.md /usr/local/share/doc/kai-cli/; \
  cd / && rm -rf "$work"; \
  fx --version
COPY fx-acp.mjs fx-host.mjs mcp-check.mjs agent-browser-mcp.mjs /opt/dotrix/

# A browser for the agent (the platform passes it as an MCP server, `playwright-mcp`): Playwright's
# Chromium, headless, in a shared folder the unprivileged user can run. It opens the app the agent
# serves on localhost inside the sandbox; the sandbox's network rules still apply to everything else.
ARG PLAYWRIGHT_MCP_VERSION=0.0.85
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
