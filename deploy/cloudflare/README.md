# Cloudflare staging pilot

The Workers deployment serves separate web, admin, and marketing preview origins. The web app uses `cf-pilot.dotrix.cc`, the admin uses `cf-admin-pilot.dotrix.cc`, and the marketing preview uses `cf-site-pilot.dotrix.cc`. One FastAPI container serves both authorized API routes. A Railway worker runs Nova jobs and queued emails. Neon Postgres, Redis Cloud, and R2 hold staging data. The internal VPS and production use separate services and credentials.

## Provision staging

- Create a Neon project with a direct Postgres endpoint and permission to enable `vector`. Use the same URL for the API, worker, and migration. Write it as `postgresql+psycopg://USER:PASSWORD@NEON_DIRECT_HOST/DB?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt`. The backend image installs this CA bundle, and libpq uses it to verify Neon's certificate and hostname for both SQLAlchemy and the LangGraph checkpointer. Start on Neon Free and watch its CU-hours allowance.
- Create one paid Redis Cloud Essentials database with TLS enabled and client authentication by Redis username and password. Download the CA bundle. Use the provider hostname in the `rediss://` URL, and store the PEM text with the original line breaks.
- Create the private R2 bucket `dotrix-cf-pilot` and bucket-scoped read/write credentials. Generate a new high-entropy JWT secret and a Fernet encryption key.
- In Cloudflare Email Service, onboard a staging sender domain for **Email Sending** and wait for DNS verification. Create an account-scoped API token with **Email Sending Write**. Use the sending account ID, that token, and the bare sender address in `staging-secrets.json`. Railway sends queued messages through the HTTPS API. Workers Paid permits sending to regular signup addresses. [Cloudflare Email Sending setup](https://developers.cloudflare.com/email-service/get-started/send-emails/)
- Create an always-on Railway worker service with private GHCR read access. Railway currently requires Pro to pull a private image, which starts at $20/month and includes that amount in usage. With the earlier light-use assumptions, budget about $30/month for Cloudflare, Railway, Redis and Neon Free. [Railway private registry requirements](https://docs.railway.com/builds/private-registries)
- Create a Cloudflare Access self-hosted application for the entire `cf-admin-pilot.dotrix.cc` hostname. Allow only staging operators. Set `DOTRIX_ACCESS_ISSUER` to the team's `https://TEAM.cloudflareaccess.com` URL with no trailing slash and `DOTRIX_ACCESS_AUDIENCE` to the application's AUD tag. The Worker verifies the signed Access assertion before serving admin assets or API routes. Dotrix admin login and 2FA still apply. Set a separate `DOTRIX_ADMIN_BOOTSTRAP_TOKEN` for first-admin setup. [Cloudflare Access token validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)

## Release the staging image and site

From a clean checkout of the reviewed revision, use Node, pnpm, Docker Buildx and Wrangler 4.136.0 or later. Authenticate Wrangler for the staging Cloudflare account and Docker for private GHCR. Export `KAI_PACKAGES_TOKEN` with access to the Kai package, `CLOUDFLARE_ACCOUNT_ID`, and `DOTRIX_WORKER_IMAGE_REPOSITORY` (a private GHCR repository such as `ghcr.io/OWNER/dotrix-backend`).

```bash
tag="sha-$(git rev-parse --short=12 HEAD)"
docker buildx build --platform linux/amd64 --load \
  --file deploy/backend.Dockerfile \
  --secret id=kai_packages_token,env=KAI_PACKAGES_TOKEN \
  --tag "dotrix-backend:$tag" .
docker tag "dotrix-backend:$tag" "$DOTRIX_WORKER_IMAGE_REPOSITORY:$tag"
docker push "$DOTRIX_WORKER_IMAGE_REPOSITORY:$tag"
npx wrangler@4.136.0 containers push "dotrix-backend:$tag"
```

Use the Cloudflare registry's `sha256:…` manifest digest printed by Wrangler or listed in its image registry. Record the Cloudflare digest and the GHCR digest with the source commit. Both images come from the same local build. Use the digest in the Railway service's private source image reference.

Copy `staging-secrets.example.json` to the ignored `staging-secrets.json`, fill it with staging values, and restrict file access. Export the matching staging `DOTRIX_DATABASE_URL` in your shell for the one-shot release job.

```bash
docker run --rm --env DOTRIX_DATABASE_URL --workdir /app/apps/backend \
  "dotrix-backend:$tag" alembic upgrade head
docker run --rm --env DOTRIX_DATABASE_URL --workdir /app/apps/backend \
  "dotrix-backend:$tag" alembic check
```

In Railway, set the start command to `python -m dotrix_backend.worker` and configure one replica with sleep disabled and no public domain. Set the same values from `staging-secrets.json` as runtime variables. Also set `DOTRIX_APP_URL=https://cf-pilot.dotrix.cc`, `DOTRIX_ENV=staging`, `DOTRIX_JOBS=worker`, `DOTRIX_RATE_LIMITS=redis`, `DOTRIX_CODING_SANDBOX=off`, `DOTRIX_EMAIL_BACKEND=cloudflare`, and `DOTRIX_S3_REGION=auto`. Verify the worker connects and starts processing before deploying the API.
Set `DOTRIX_ADMIN_URL=https://cf-admin-pilot.dotrix.cc` for operator links and `DOTRIX_DEPLOYMENT_REVISION` to the full SHA of the deployed worker image. Keep the Access settings and bootstrap token on the Cloudflare side.

```bash
node deploy/cloudflare/build-assets.mjs
node deploy/cloudflare/configure.mjs "$CLOUDFLARE_ACCOUNT_ID" "$DOTRIX_CLOUDFLARE_IMAGE_DIGEST" "$(git rev-parse HEAD)"
npx wrangler@4.136.0 deploy --config deploy/cloudflare/wrangler.generated.json \
  --secrets-file deploy/cloudflare/staging-secrets.json
```

The generated config attaches only the three pilot hostnames. Changing API runtime secrets requires a fresh container process. For a controlled rotation, redeploy, let the instance sleep, and verify the next start.

### Website analytics and downloads

Create a separate Cloudflare Web Analytics site for each environment. Use manual beacon setup and disable automatic beacon injection and any other automatic RUM for that marketing hostname so the consent choice controls collection. Set `VITE_CLOUDFLARE_WEB_ANALYTICS_TOKEN` to the public token from the manual snippet when running `node deploy/cloudflare/build-assets.mjs`. For Dokploy, set it in the site's build environment.

Set `DOTRIX_CLOUDFLARE_ANALYTICS_ACCOUNT_ID`, `DOTRIX_CLOUDFLARE_ANALYTICS_SITE_TAG` (the site's identifier, distinct from the public beacon token), and `DOTRIX_CLOUDFLARE_ANALYTICS_API_TOKEN` (account Analytics Read) on the API. In the Cloudflare pilot these are optional Worker bindings. If omitted, Admin reports the traffic source as unconfigured and still fetches the public GitHub download counts. Keep the API token in the server environment.

On a clean browser profile, confirm the marketing page sends no Cloudflare analytics requests before consent or after rejection. Accept analytics, verify the beacon loads, then reject via Cookie settings and confirm it remains off after reload. Allow time for the aggregate to appear in Admin → Overview. GitHub download totals include supported installer and archive assets from stable releases and can include repeated downloads and desktop updates.

## Verify and record results

1. Request `/health` and `/health/ready` on the app origin. Check that the readiness response reports Postgres reachable. Visit a deep workspace URL directly. On the marketing preview, open the signup link and confirm it points to the pilot. Confirm the app origin returns 404 for `/v1/admin/bootstrap` and the admin hostname requires Cloudflare Access before admin login and 2FA.
2. Create a staging user. Confirm Cloudflare Email Sending delivers the verification email, then follow the link, sign in, refresh the session, create a project, and upload and download a file. Request a password-reset email and confirm that link works too. Under the test user's own model key, complete a Nova Chat turn and confirm events arrive before the final reply. Verify cloud Codes is unavailable.
3. Leave the API idle for more than five minutes without external probes. Reopen the workspace. Confirm the API's uptime reset and the user's session, records, and files still work. Repeat after a staging API redeploy.
4. Start a Nova turn and restart the Railway worker while the run is active. Confirm job recovery and one run record for the request. Check the worker logs for a Postgres checkpointer fallback or Redis certificate errors.
5. In admin Overview, confirm the API and worker commits match, the heartbeat is recent, and the email acceptance timestamp updates. Email numbers show provider acceptance and scheduled job retries, with permanent provider rejections counted separately. Compare the last claimed dispatch's queue wait and Nova's mean time from stream open to first event. The email and Nova counters reset at midnight UTC.
6. Run **Desktop and CLI builds** on the pilot branch with `staging` checked and the release tag empty. Download the staging artifact for each client. The portable desktop build uses a separate profile and has automatic updates disabled. Check desktop sign-in, runner registration, and a local Codes turn with its bundled CLI. For the standalone CLI, check device login, `dotrix whoami`, project linking in a throwaway checkout, and runner heartbeat. An installed CLI can also point to staging through `DOTRIX_API_URL=https://cf-pilot.dotrix.cc`.
7. For seven days record cold-start latency from Worker events named `dotrix_api_cold_start`, Nova first-event timings, Cloudflare container awake hours, Railway average CPU and RAM, Neon CU-hours, and total billed usage. Review these results before scheduling a production cutover.

To roll back an application release, deploy the previous Cloudflare image digest and matching web build from that revision and restore the matching GHCR image on Railway. If the previous image cannot use the migrated schema, pause staging and use the Neon restore point taken before the release. Wait for the restored worker to connect before reopening the staging site. The reviewed code moves from `stage` to `main` through the normal release PR after the pilot passes. Production data and DNS cutover are separate release steps.
