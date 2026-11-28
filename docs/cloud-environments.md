# Dotrix coding environments

Status: the first bounded cloud profile is implemented. In Settings → Environments
& network, select a project to configure its enabled profile, name, setup script,
verification command and per-script time limit. Saving requires workspace
administrator permission and rejects stale revisions. The database migration must
be applied before using these endpoints.

Each new cloud session pins the profile before approval and shows its scripts in
the brief; follow-ups retain that snapshot. Local sessions ignore cloud profiles.
Environment ownership is independent of a published branch or PR. Plan/no-change
turns and branch rollover keep the first cloud admission's profile, including an
admitted absence of a profile. Local turns do not apply or erase it; a session
that starts locally pins a profile only on its first cloud admission. The last
resolved image for that admitted profile survives later attempts.

Setup runs only in a supported isolated sandbox, never the development local
process backend. Setup must leave tracked and non-ignored repository files clean;
use frozen installs and ignored dependency/cache directories. Verification runs
after Kai with the existing Linux Landlock ABI 3 read-only filesystem boundary; use `$TMPDIR` for
artifacts and `python -B` for Python checks. A failed, timed-out or cancelled phase
prevents publication. Activity shows phase status, without raw script output.
Environment versions participate in sandbox reuse. Parallel coding currently
refuses enabled profiles rather than bypassing setup or verification.

Profiles sit beside the project's network policy (`coding/network.py`, one format
with the local runner in `dotrix_engine/network_policy.py`). The workspace may set
a limit, the most any project may allow; the project chooses its hosts within it;
and a coding session pins that choice when its first turn is admitted, for every
follow-up, cloud or local, while the limit as it is now still applies to each
turn. On Docker, the operator can approve
additional images by registry digest. The worker resolves the selected image to
an immutable local content ID, records that ID on the run, and uses it for both
agent and egress containers. Retries and follow-ups retain that ID. A platform
default specified by a mutable tag is resolved at first execution, not at approval.
No fallback image is substituted when that content ID is unavailable. Removing
an image from the operator list blocks new admission and execution of queued runs.

Environment variables (non-secret `KEY=value` pairs, edited in `.env` format) are
set for the setup script, Kai's commands and verification. They are shown in the
brief, so names that look like secrets are refused, as are names the sandbox or
the coding tools use. The same form saves the project's network policy.

## Host secrets

A host secret (`coding/secrets.py`, Secrets in the same form, `PUT/DELETE
.../coding/secrets/{NAME}`, owners and admins) is a value for one exact host in
the project's network policy: a private registry's token, a test API's key. The
sandbox never holds it. Kai's commands see a placeholder in the variable `NAME`
and send it as the host expects (`Authorization: Bearer $NPM_TOKEN`); the
sandbox's proxy puts the real value into that header on requests to that host
only:

- Docker Cloud stores it as a custom secret injected into its host's requests
  (`hosts`, `header`, `format` = prefix + value, `envVar`), as it stores the
  model key, and deletes it with the sandbox.
- OpenShell imports a provider profile made for the turn (the host inspected
  with `protocol: rest`, `auth_style: bearer` or `header`), creates a provider
  from it with the value passed by environment, attaches it beside the model
  key's provider, and deletes both afterwards. The host is then left out of the
  policy's relayed (`tls: skip`) endpoints.
- The local sandbox refuses a turn with secrets; people's computers never get
  them; parallel builds refuse them for now.

Values are encrypted with `DOTRIX_ENCRYPTION_KEY`, never returned, logged or put
in a brief, and changes are audited (`coding_secret.created`, `.updated`,
`.deleted`) by name and host only. A secret's name can't be one of the
environment's variables, nor a name the sandbox or tools use. A coding session
pins its project's secrets (names, hosts, headers; `coding_runs.secret_snapshot`)
with its first turn; each turn reads the current values, so a rotated value
reaches running sessions, while a secret whose host or header changed, that was
deleted, or whose host the turn's network policy no longer allows, is left out
and the turn says why. A sandbox opened with other secret versions isn't reused.
Neither sandbox's injection has run on a real gateway or account yet.

### Shared secrets

Owners and admins can keep a secret once for the workspace
(`PUT/DELETE /v1/workspaces/{id}/coding/shared-secrets/{NAME}`, Settings →
Environments & network with Workspace limit selected). Its host must be within
the workspace's network limit when there is one. A project uses it only by
referencing it by name (`PUT .../coding/secrets/{NAME}` with `shared: true`,
"A workspace shared secret" in the form); the reference stores no host or
value, and the shared secret's host must be in the project's network access.
Turns read the shared secret's current value, so rotating it once reaches
every project that references it on its sessions' next turns. Deleting it
leaves the references, listed as missing, and turns go on without it. Changes
are audited as `coding_shared_secret.*`.

### Setup-only secrets

A project's own secret or its reference to a shared one can be `phase:
setup` ("Only for the setup script"). It goes to the sandbox only on a fresh
sandbox whose environment has a setup script that runs this turn (never in
Plan, never to a warm or woken sandbox), and is removed before Kai runs: on
Docker Cloud the Docker secret is deleted and checked gone and its placeholder
leaves later commands' environment; on OpenShell its provider is detached
(`openshell sandbox provider detach`) and deleted with its profile. A failed
removal stops the turn before Kai starts. Kai's brief never names a setup-only
secret. On OpenShell its host, which only its provider supplied, is unreachable
after setup.

This slice does not implement arbitrary unreviewed images, multiple selectable
profiles, or dependency-only network phases. Do not put secrets in scripts or variables: scripts are shared project configuration and appear in private run
briefs. The broader contract below remains the implementation plan for those
remaining capabilities. These tests use disposable repositories and scripted
engine/container transports, not proof of deployed sandbox behavior.

## Approving a project image

Custom images currently require the OpenShell sandbox (Docker Cloud uses the platform image). Build them from the supported
`infra/coding/Dockerfile` contract, including every pinned engine, the browser,
`/opt/dotrix` drivers, and the sandbox user. Review the image before allowing it;
image approval grants executable code access to admitted runs and their model key.
Do not bake credentials into an image.

1. Push the reviewed image to your registry and obtain its immutable registry digest.
2. Make that exact digest available to the OpenShell gateway. Registry credentials
   belong to the operator and the gateway, never to the coding sandbox.
3. Set `DOTRIX_CODING_ENVIRONMENT_IMAGES` to a JSON list of approved references
   such as `registry.example.com/team/coding@sha256:<64 lowercase hex digits>`.
   Restart API and workers with the same list; Dokploy passes it to both.
4. Select that image in the project's environment editor. Tags such as `latest`
   cannot be selected as custom images. New sessions pin the selection in the
   approval brief; changing a project profile does not change existing sessions.

Image resolution never mutates the shared sandbox factory. The resolved image ID
participates in warm reuse, preventing a warm container built from another image
from being reused. Environments on other sandbox implementations continue to use
the platform image; custom-image selection fails explicitly there.

## Cloud and local

A cloud environment describes the reproducible computer Kai gets for a repository.
Start with one project environment: a platform-reviewed image pinned by digest,
a reviewed setup script, a verification command, non-secret variables, encrypted
secret references and explicit network presets/hosts. Reuse the existing project
repository connection. Do not make setup a prerequisite for ordinary Chat.

A local session uses the selected checkout and tools already installed on the
person's computer. It does not need a cloud environment. Later, let the desktop
runner explicitly opt into a compatible profile; never apply cloud secrets or
run setup on a person's computer automatically. Native fx is currently disabled because its web-access policy could not be enforced;
cloud fx remains available.
Use a supported isolated runtime when commands are required.

## Remaining full environment contract

- Project settings → Environments: list, create, edit, validate and archive a
  project-scoped profile. Use Dotrix's existing controls. Show the image,
  repository, setup script, test command and network policy before saving.
- Only authorized project administrators may change executable configuration or
  secret references. Audit edits without secret values. Workspace network policy
  caps each project's choices; inherit existing package-manager presets.
- Select an environment when starting Codes. Pin its version and image digest on
  the run before approval. A saved edit creates a new version; queued and resumed
  runs retain their original snapshot. Warm reuse includes the environment digest.
- Setup runs inside the supported sandbox with a separate bounded timeout, process
  cancellation and streamed activity. Its failure stops the turn before Kai runs;
  its changed files must not enter the model's patch. Preserve an explicit baseline.
- Separate dependency-install network access from model execution. Enforce each
  phase's policy at the actual network boundary. Do not give arbitrary public
  internet access to a container that holds a model key.
- Keep secret values in the platform vault. Return names and status only. Bind
  access to the requester, workspace, project and admitted run. Avoid shell
  interpolation, command-line values and raw environment dumps. Prefer brokered
  credentials; use narrowly scoped disposable install credentials where needed.
- Setup has no GitHub push/merge authority. Preserve Manual approvals and the
  worker's patch guard. Failed/cancelled setup or turns cannot publish partial work.
- Validate image/tool availability, disk space for the agent and egress containers,
  required isolation runtime, provider connectivity, and required secrets before
  executing. Report actionable failures without falling back to weaker isolation.

## Remaining implementation order

1. Extend the implemented project profile with multiple selectable versions and
   encrypted secret-reference models; retain administrator checks and audit.
2. Extend immutable run snapshots and environment-aware reuse with image-digest
   pinning and preflight.
3. Implement bounded setup/verification phases and separate network/secret lifetimes.
4. Extend the settings editor with profile lists and a Codes environment selector.
5. Verify cross-project isolation, stale edits, approval/recovery, setup failure,
   cancellation, secret redaction and browser artifacts with real sandbox runs.

Do not ship a configuration-only screen that implies these execution guarantees exist.

## Web search

Use a private, self-hosted [SearXNG](https://docs.searxng.org/) service. It is an
open-source metasearch engine: it queries other search engines rather than
maintaining an independent web index. Upstream rate limits and bot challenges
still apply. Self-hosting avoids a search API subscription, but requires compute
and maintenance.

SearXNG now ships with the Docker stacks. Its pinned multi-platform image and
inline settings enable JSON; it needs no search API subscription. Set a unique
server secret before starting either stack:

```sh
openssl rand -hex 32
```

Put the result in `SEARXNG_SECRET` in the root `.env` (native/development) or
Dokploy's environment variables (production). This signs SearXNG state; it is
separate from personal model keys. Do not commit the generated value.

- Native development: `pnpm db:up` starts it alongside Postgres, Redis and storage.
  The native API and worker use `DOTRIX_SEARCH_PROVIDER=searxng` and
  `DOTRIX_SEARXNG_URL=http://127.0.0.1:8081` from `.env`. Only loopback is published.
- Docker development: `pnpm docker:up` connects both API and worker to
  `http://searxng:8080` and waits for its health check.
- Dokploy: deploy the updated Compose file after setting `SEARXNG_SECRET`.
  API and worker use the same internal address. Do not assign SearXNG a public
  domain or publish its port. No separate search installation is needed.

`DOTRIX_SEARXNG_PORT` can change the native port; update the native URL to match.
The image digest is pinned in both Compose files; update both after validating
`/healthz` and a JSON query. The service uses upstream engines, so it needs
outbound HTTPS. If your host intercepts TLS, install its trusted CA bundle in the
search container using your normal infrastructure configuration; never disable
certificate verification. Container health verifies the service, not upstream
search-engine availability.

Test `/search?q=python&format=json` from the API and worker containers. A 403
usually means JSON output or service access is not configured. Search results
retain Dotrix source IDs, limits and untrusted-content handling. Pages still go
through Dotrix's public-address-checking page reader. Recency is an upstream
coarse time range, not a guarantee that every result was published within N days.

This integration serves Nova and permitted research tools on both chat runtimes.
It does not yet give cloud Kai a new search MCP connection. That requires a
platform-owned, per-run authenticated tool connection, keeping service credentials
outside the coding repository and preserving network and approval boundaries.
