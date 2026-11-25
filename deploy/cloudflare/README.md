# Cloudflare staging pilot

The Workers deployment serves the web build and forwards `/api`, `/v1`, and `/health` to one FastAPI container. A Railway worker runs Nova jobs and sends queued emails. Neon Postgres, Redis Cloud, and R2 hold staging data. The pilot uses `cf-pilot.dotrix.cc`; the internal VPS and production use separate services and credentials.

## Provision staging

- Create a Neon project with a direct Postgres endpoint and permission to enable `vector`. Use the direct endpoint for the app and migration. Write the URL as `postgresql+psycopg://…?sslmode=verify-full` so the existing SQLAlchemy and LangGraph connections can share it. Start on Neon Free and watch its CU-hours allowance.
- Create one paid Redis Cloud Essentials database with TLS enabled and client authentication by Redis username and password. Download the CA bundle. Use the provider hostname in the `rediss://` URL, and store the PEM text with the original line breaks.
- Create the private R2 bucket `dotrix-cf-pilot` and bucket-scoped read/write credentials. Give staging its own Sendly key and verified From address. Generate a new high-entropy JWT secret and a Fernet encryption key.
- Create an always-on Railway worker service with private GHCR read access. Railway currently requires Pro to pull a private image, which starts at $20/month and includes that amount in usage. With the earlier light-use assumptions, budget about $30/month for Cloudflare, Railway, Redis and Neon Free. [Railway private registry requirements](https://docs.railway.com/builds/private-registries)

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

In Railway, set the start command to `python -m dotrix_backend.worker` and configure one replica with sleep disabled and no public domain. Set the same values from `staging-secrets.json` as runtime variables. Also set `DOTRIX_APP_URL=https://cf-pilot.dotrix.cc`, `DOTRIX_ENV=staging`, `DOTRIX_JOBS=worker`, `DOTRIX_RATE_LIMITS=redis`, `DOTRIX_CODING_SANDBOX=off`, `DOTRIX_EMAIL_BACKEND=sendly`, and `DOTRIX_S3_REGION=auto`. Verify the worker connects and starts processing before deploying the API.

```bash
pnpm build:web
node deploy/cloudflare/configure.mjs "$CLOUDFLARE_ACCOUNT_ID" "$DOTRIX_CLOUDFLARE_IMAGE_DIGEST"
npx wrangler@4.136.0 deploy --config deploy/cloudflare/wrangler.generated.json \
  --secrets-file deploy/cloudflare/staging-secrets.json
```

The generated config attaches only `cf-pilot.dotrix.cc`. Keep the public app hostname on its current origin. Changing API runtime secrets requires a fresh container process. For a controlled rotation, redeploy, let the instance sleep, and verify the next start.

## Verify and record results

1. Request `/health` and `/health/ready`. Check that the readiness response reports Postgres reachable. Visit a deep workspace URL directly and verify the frontend loads.
2. Create a staging user. Follow the verification email, sign in, refresh the session, create a project, and upload and download a file. Under the test user's own model key, complete a Nova Chat turn and confirm events arrive before the final reply. Verify cloud Codes is unavailable.
3. Leave the API idle for more than five minutes without external probes. Reopen the workspace. Confirm the API's uptime reset and the user's session, records, and files still work. Repeat after a staging API redeploy.
4. Start a Nova turn and restart the Railway worker while the run is active. Confirm job recovery and one run record for the request. Check the worker logs for a Postgres checkpointer fallback or Redis certificate errors.
5. For seven days record cold-start latency, time to first Nova event, Cloudflare container awake hours, Railway average CPU and RAM, Neon CU-hours, and total billed usage. Review these results before scheduling a production cutover.

To roll back an application release, deploy the previous Cloudflare image digest and matching web build from that revision and restore the matching GHCR image on Railway. If the previous image cannot use the migrated schema, pause staging and use the Neon restore point taken before the release. Wait for the restored worker to connect before reopening the staging site. The reviewed code moves from `stage` to `main` through the normal release PR after the pilot passes. Production data and DNS cutover are separate release steps.
