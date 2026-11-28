# syntax=docker/dockerfile:1
# The API, the worker, and migrations: one image, three commands (deploy/docker-compose.dokploy.yml).
#
#   docker build -f deploy/backend.Dockerfile -t dotrix-backend .
#
# The worker codes in Docker Cloud sandboxes over Docker's HTTP API, so the image carries git (for checkouts) but no
# Docker CLI. uv's download cache is a build cache mount, never a layer: it was half a gigabyte of the image.
#
# Chat's fx host installs the Kai runtime (@kunemi-group/kai) from GitHub Packages, which needs a token with
# read:packages, passed as a build secret so it stays out of the image's layers:
#
#   docker build -f deploy/backend.Dockerfile --secret id=kai_packages_token,env=KAI_PACKAGES_TOKEN -t dotrix-backend .
FROM node:22-bookworm-slim AS fx-host
WORKDIR /fx
COPY packages/engine/src/dotrix_engine/runtimes/fx_host/package.json packages/engine/src/dotrix_engine/runtimes/fx_host/package-lock.json packages/engine/src/dotrix_engine/runtimes/fx_host/.npmrc ./
RUN --mount=type=secret,id=kai_packages_token,required=true \
  NODE_AUTH_TOKEN="$(cat /run/secrets/kai_packages_token)" npm ci --omit=dev

FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/
COPY --from=fx-host /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
  && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /app

# The workspace's manifests first, so dependencies are cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
COPY packages/engine/pyproject.toml packages/engine/
COPY apps/cli/pyproject.toml apps/cli/
COPY apps/backend/pyproject.toml apps/backend/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-workspace --package dotrix-backend

COPY packages/engine packages/engine
COPY --from=fx-host /fx/node_modules packages/engine/src/dotrix_engine/runtimes/fx_host/node_modules
COPY apps/backend apps/backend
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --package dotrix-backend

ENV PATH=/app/.venv/bin:$PATH
RUN useradd --uid 10001 --create-home dotrix \
  && mkdir -p /data/code && chown dotrix:dotrix /data/code && chmod 700 /data/code
USER dotrix
EXPOSE 8000
CMD ["python", "-m", "dotrix_backend.serve", "--host", "0.0.0.0", "--port", "8000"]
