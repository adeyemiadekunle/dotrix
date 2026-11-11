# Plan 007: The web app and admin console are served with anti-framing and hardening headers

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- deploy/nginx.conf deploy/admin.nginx.conf`
> If either file changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition. (Plan 001 adds a `location ~ ^/v1/admin` block to
> `deploy/nginx.conf`; if that is the only difference, continue and keep it.)

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (touches `deploy/nginx.conf`, as plan 001 does — do them one after the other, not in parallel)
- **Category**: security
- **Planned at**: commit `f477722`, 2026-11-11

## Why this matters

The web app (`app.dotrix.cc`) keeps the session in cookies and has one-click
actions with real consequences: approving an agent's change, "Accept and push",
deleting a project. Its nginx sends no header that stops another website from
loading it in an invisible frame and tricking a signed-in person into clicking
(clickjacking). The admin console's nginx is the same. The public site's nginx
already sets two hardening headers, so this is an omission, not a decision.

After this plan both origins send `X-Frame-Options: DENY`, a
`frame-ancestors 'none'` policy, `X-Content-Type-Options: nosniff` and a
`Referrer-Policy`, on every response including proxied API responses.

A full Content-Security-Policy that restricts scripts and styles is
deliberately **not** part of this plan (see Maintenance).

## Current state

- `deploy/nginx.conf` — the web app and API on one origin (copied into the image by `deploy/web.Dockerfile:16`).
- `deploy/admin.nginx.conf` — the admin console (copied by `deploy/admin.Dockerfile:16`).
- `deploy/site.nginx.conf` — the public site; already has, at server level (lines 10-11):

```nginx
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
```

`deploy/nginx.conf` today (whole file):

```nginx
# The web app and the API on one origin. Traefik (Dokploy) terminates TLS in front of this.
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;

    # Docker's DNS, looked up per request: nginx starts even while the API is still starting.
    resolver 127.0.0.11 valid=10s ipv6=off;
    set $api http://api:8000;

    client_max_body_size 30m;  # uploads: DOTRIX_MAX_UPLOAD_MB is 25 by default

    location ~ ^/(v1|api|health)(/|$) {
        proxy_pass $api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        # Agent runs stream (server-sent events): pass them through as they come.
        proxy_buffering off;
        proxy_read_timeout 1h;
    }

    # Built files are named by their content: cache them for good.
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }

    # Every other path is the single-page app.
    location / {
        add_header Cache-Control "no-cache";
        try_files $uri /index.html;
    }
}
```

`deploy/admin.nginx.conf` has the same shape: a proxied
`location ~ ^/v1/admin(/|$)`, a `location ~ ^/(v1|api|health)(/|$) { return 404; }`,
then the same `/assets/` and `/` locations with their own `add_header Cache-Control`.

**The nginx rule that makes this easy to get wrong:** `add_header` directives
are inherited from the `server` level **only by locations that define no
`add_header` of their own**. The `/assets/` and `/` locations each define one
(`Cache-Control`), so server-level headers would silently not apply to
`index.html` — the one response that matters most. The headers must therefore
be repeated inside every location that has its own `add_header`.

Facts that make `DENY` safe here: the desktop app loads the web app as a
top-level Electron window, not in a frame; the public site shows screenshots
(images), not a framed app. A search for `<iframe` in `apps/web/src`,
`apps/admin/src` and `apps/site/src` should find no frame that embeds the app
itself (Step 1 checks).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Syntax check (needs Docker) | `docker run --rm -v "$PWD/deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t` | `syntax is ok` / `test is successful` |
| Same for admin | `docker run --rm -v "$PWD/deploy/admin.nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t` | same |
| Format check | `pnpm format:check` | exit 0 (nginx files are not formatted by Prettier; this guards the CHANGELOG edit) |

## Scope

**In scope**:

- `deploy/nginx.conf`
- `deploy/admin.nginx.conf`
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- `deploy/site.nginx.conf` — already has its headers; the site is public content.
- The backend (`apps/backend`) — headers are set at the edge, once.
- A script/style Content-Security-Policy, `Strict-Transport-Security` (TLS ends at Traefik in front of nginx; HSTS belongs there), and `Permissions-Policy`.
- `infra/` compose files and the Dockerfiles — they copy these two config files as they are.

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/007-security-headers origin/stage`. PRs go into `stage`, never `main`.
- Commit message: one short sentence-case line (e.g. `nginx: anti-framing and hardening headers on the app and the admin console`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm nothing frames the app

Run: `grep -rn "<iframe" apps/web/src apps/admin/src apps/site/src apps/desktop/src | head`

**Verify**: no result embeds the dotrix app's own origin in a frame. (An iframe
that shows *other* content inside the app, such as a preview, is unaffected:
these headers govern who may frame **us**.) If something does frame the app
itself, STOP and report it.

### Step 2: Add the headers to `deploy/nginx.conf`

Add at server level, after the `client_max_body_size` line:

```nginx
    # Nobody frames the app (its buttons approve and push changes), and browsers don't guess types.
    # Repeated in each location below that sets a header of its own: nginx inherits add_header
    # only into locations that have none.
    add_header X-Frame-Options DENY always;
    add_header Content-Security-Policy "frame-ancestors 'none'" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
```

Then add the same four `add_header … always;` lines inside the `/assets/`
location and inside the `/` location, next to their existing
`add_header Cache-Control …` line (keep that line). Do not add them inside the
proxied `location ~ ^/(v1|api|health)(/|$)` block: it has no `add_header`, so
it inherits the server-level ones. If plan 001's `location ~ ^/v1/admin` block
(a bare `return 404;`) is present, leave it as it is.

**Verify**:
- `grep -c "X-Frame-Options DENY always" deploy/nginx.conf` → `3`
- `grep -c "frame-ancestors 'none'" deploy/nginx.conf` → `3`
- `grep -c "X-Content-Type-Options nosniff always" deploy/nginx.conf` → `3`
- `grep -c "Referrer-Policy strict-origin-when-cross-origin always" deploy/nginx.conf` → `3`

### Step 3: Add the same to `deploy/admin.nginx.conf`

Same edit: four lines at server level (after the `set $api …` line, with the
same comment, saying "the console" instead of "the app"), and the same four
lines inside its `/assets/` and `/` locations. Leave the two API locations
unchanged.

**Verify**: the same four `grep -c` commands against `deploy/admin.nginx.conf` → `3` each.

### Step 4: Syntax and behaviour check

**Verify (if Docker is available)**: both `nginx -t` commands from the table
print `syntax is ok`. Then check a real response:

```bash
docker run -d --rm --name dotrix-nginx-check -p 18080:80 \
  -v "$PWD/deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine
sleep 1
curl -sI http://127.0.0.1:18080/ | grep -i -E "x-frame-options|content-security-policy|x-content-type-options|referrer-policy|cache-control"
docker stop dotrix-nginx-check
```

Expected: all five header names appear once each (the stock image's
`index.html` answers `/`). If Docker is not available, skip this step, rely on
the `grep -c` checks, and say so in your report — do not claim the syntax check
passed.

### Step 5: Changelog

Under `## [Unreleased]` → `### Security` in `CHANGELOG.md` add:
`- The app and the admin console can no longer be shown inside another website's frame, and they send stricter content-type and referrer headers.`

**Verify**: `python scripts/release.py check` → exit 0, and `pnpm format:check` → exit 0

## Test plan

There is no automated test harness for the nginx configs in this repo. The
checks are the `grep -c` counts (Steps 2-3) and, where Docker is available,
`nginx -t` plus the `curl -I` header check (Step 4). Do not add a new CI job in
this plan.

## Done criteria

- [ ] Each of the four header lines appears exactly 3 times in `deploy/nginx.conf` and 3 times in `deploy/admin.nginx.conf`
- [ ] Both existing `add_header Cache-Control` lines in each file are still present
- [ ] `nginx -t` passes for both files, **or** the report states Docker was unavailable
- [ ] `git status --short` lists only the three in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- The excerpts in "Current state" do not match the live files (other than plan 001's added block).
- Step 1 finds the app framing itself, or a product surface that must be embedded elsewhere.
- `nginx -t` reports an error you cannot fix by correcting a typo in the lines you added.

## Maintenance notes

- Anyone adding a new `location` with its own `add_header` must repeat the four lines there; a reviewer should check for that. If the list grows, move the four lines into a snippet file and `include` it (which also requires a `COPY` line in `deploy/web.Dockerfile` and `deploy/admin.Dockerfile`).
- Deferred on purpose: a script/style Content-Security-Policy. The app sets inline `style` attributes widely and loads fonts, so a real CSP needs an inventory of what the pages load and a pass over the app; do it as its own plan, starting in `Content-Security-Policy-Report-Only`.
- Deferred: `Strict-Transport-Security`, to be set at Traefik (Dokploy), where TLS terminates.
- The Vite dev server (`pnpm dev:web`) does not send these headers; only the nginx images do.
