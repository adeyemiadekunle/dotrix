# The public site (dotrix.cc), prerendered and served by nginx. It talks to no API: its links go
# to the web app (VITE_APP_URL, https://app.dotrix.cc) and the latest release's downloads.
#
#   docker build -f deploy/site.Dockerfile -t dotrix-site .
FROM node:22-bookworm-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH ELECTRON_SKIP_BINARY_DOWNLOAD=1 CI=1
RUN corepack enable && corepack prepare pnpm@11.1.2 --activate
ARG VITE_APP_URL=https://app.dotrix.cc
ARG VITE_DOWNLOADS_URL=https://github.com/adeyemiadekunle/dotrix/releases/latest
ENV VITE_APP_URL=$VITE_APP_URL VITE_DOWNLOADS_URL=$VITE_DOWNLOADS_URL
WORKDIR /src
COPY . .
RUN pnpm install --frozen-lockfile --filter "@dotrix/site..." \
  && pnpm --filter @dotrix/site build

FROM nginx:1.27-alpine
COPY deploy/site.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/apps/site/dist /usr/share/nginx/html
EXPOSE 80
