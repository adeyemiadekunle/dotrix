# The image coding runs use in OpenShell (DOTRIX_CODING_IMAGE): Claude Code, Codex, git, and
# common toolchains so the agent can run a project's tests. Add what your projects need.
#
#   docker build -t dotrix-coding:latest infra/coding
#
# No credentials are baked in: the model key is attached per run as an OpenShell provider, and
# the agent never gets a GitHub token (the worker clones and pushes outside the sandbox).
# The full Debian image already has git, curl, Python 3, and a C toolchain.
FROM node:22-bookworm

# The CLIs, installed globally; their binaries are what the provider profiles allow to reach
# the model APIs (see dotrix-claude-code.yaml and dotrix-codex.yaml).
RUN npm install -g @anthropic-ai/claude-code @openai/codex && claude --version && codex --version

# OpenShell drops the agent to this user (policy: run_as_user/run_as_group "sandbox").
RUN groupadd --gid 1500 sandbox && useradd --uid 1500 --gid sandbox --home-dir /sandbox --create-home sandbox
WORKDIR /sandbox
USER sandbox

# The sandbox supervisor replaces CMD; coding runs start `sleep infinity` and exec the agent.
CMD ["sleep", "infinity"]
