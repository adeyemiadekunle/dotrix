# The Ops app, built and served by nginx on its own origin — never bundled into the web
# app. Only /v1/ops/* forwards to the API (deploy/ops.nginx.conf); the web session API
# stays on the web app's origin.
#
#   docker build -f deploy/ops.Dockerfile -t dotrix-ops .
FROM node:22-bookworm-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH ELECTRON_SKIP_BINARY_DOWNLOAD=1 CI=1
RUN corepack enable && corepack prepare pnpm@11.1.2 --activate
WORKDIR /src
COPY . .
# Only the ops app and what it imports (the UI kit): not the web or desktop apps.
RUN pnpm install --frozen-lockfile --filter "@dotrix/ops..." \
  && pnpm --filter @dotrix/ops build

FROM nginx:1.27-alpine
COPY deploy/ops.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/ops/dist /usr/share/nginx/html
EXPOSE 80
