# The web app, built and served by nginx, which forwards /v1, /api and /health to the API on the
# same origin (the session cookies stay first-party; deploy/nginx.conf).
#
#   docker build -f deploy/web.Dockerfile -t dotrix-web .
FROM node:22-bookworm-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH ELECTRON_SKIP_BINARY_DOWNLOAD=1 CI=1
RUN corepack enable && corepack prepare pnpm@11.1.2 --activate
WORKDIR /src
COPY . .
# Only the web app and what it imports (the API client, the UI kit): not the desktop app.
RUN pnpm install --frozen-lockfile --filter "@dotrix/web..." \
  && pnpm --filter @dotrix/api-client build \
  && pnpm --filter @dotrix/web build

FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/web/dist /usr/share/nginx/html
EXPOSE 80
