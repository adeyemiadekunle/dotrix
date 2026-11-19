# The admin console (platform observability), built and served by nginx on its own origin,
# never bundled into the web app. Only /v1/admin/* forwards to the API (deploy/admin.nginx.conf);
# the web session API stays on the web app's origin.
#
#   docker build -f deploy/admin.Dockerfile -t dotrix-admin .
FROM node:22-bookworm-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH ELECTRON_SKIP_BINARY_DOWNLOAD=1 CI=1
RUN corepack enable && corepack prepare pnpm@11.1.2 --activate
WORKDIR /src
COPY . .
# Only the admin console and what it imports (the UI kit): not the web or desktop apps.
RUN pnpm install --frozen-lockfile --filter "@dotrix/admin..." \
  && pnpm --filter @dotrix/admin build

FROM nginx:1.27-alpine
COPY deploy/admin.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/admin/dist /usr/share/nginx/html
EXPOSE 80
