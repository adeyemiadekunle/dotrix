# Deploying dotrix with Dokploy

One VPS running [Dokploy](https://dokploy.com): the web app, the API, the background worker,
Postgres (with pgvector), Redis, and MinIO, and coding runs in sandboxes on the same machine's
Docker. Nobody who uses dotrix installs anything.

```
VPS
└── Docker
    ├── Dokploy, Traefik (TLS, your domain)
    ├── dotrix: site (nginx, dotrix.cc), web (nginx, app.dotrix.cc), admin (nginx, admin.dotrix.cc, /v1/ops only) → api, worker, migrate (once), postgres, redis, minio, docker-proxy
    └── coding sandboxes, two containers per run: dotrix-run-<id> and dotrix-run-<id>-egress
```

## Sizing

The defaults in `dokploy.env.example` fit 6 vCPUs and 12 GB of memory:

| What | Memory |
| --- | --- |
| Dokploy and Traefik | about 0.5 GB |
| Postgres, Redis, MinIO | about 1.5 GB |
| API and worker | about 1.5 GB |
| Coding: 2 runs at once × 3 GB (`DOTRIX_CODING_MAX_RUNS`, `DOTRIX_CODING_MEMORY`) | up to 6 GB |

A third run waits ("Waiting for a free sandbox") until one finishes. This sizing uses one cloud
worker: the two-run limit is per worker process. Idle cached sandboxes are separate: production
keeps up to one per workspace for 15 minutes. They have no coding turn executing but their Docker
containers remain running and can retain memory or background processes. Follow-ups reuse them;
an expired sandbox starts fresh and restores its saved transcript.
Every person brings their own model key. Platform token-budget settings and coding token-cap
enforcement are removed; a person can still choose a limit for their project or agent.

## Set up

1. **Dokploy:** create a project, then a **Docker Compose** service from this repository, with the
   compose path `deploy/docker-compose.dokploy.yml`.
2. **Environment:** paste `deploy/dokploy.env.example` into the service's Environment tab and fill
   it in. The GitHub App's callback and webhook URLs use your `DOTRIX_APP_URL`.
3. **Domains:** add the app's domain (`app.dotrix.cc`, the same as `DOTRIX_APP_URL`) to the `web`
   service, the public site's (`dotrix.cc`, and `www.dotrix.cc` if you like) to the `site`
   service, and the admin console's (`admin.dotrix.cc`) to the `admin` service, each on port 80
   with HTTPS. The admin console forwards only `/v1/ops` to the API; whoever operates dotrix
   creates their console account there by proving they own a workspace. Nothing else needs a domain: the API is reached through
   `web`, on the same origin. The site has no API; its Sign in, Get started and Open dotrix links go
   to `DOTRIX_APP_URL`, and its downloads to the repository's latest release.
4. **Deploy.** The first deploy builds the images on the VPS (the backend, the web app, the public
   site, the admin console, and the coding image the worker starts), runs the migrations, then starts everything.

## What survives a restart

Runs execute in the `worker`, never in the API, so redeploying either loses nothing that
matters:
- **Chat runs** hold a lease the worker renews (`DOTRIX_AGENT_LEASE_SECONDS`, 90 by default).
  When a worker stops, the next one picks the run up from its last checkpoint within about a
  minute and a half. A resumed run asks for approval before any change, so nothing goes through
  twice. After three tries the run shows Continue to whoever asked.
- **Coding runs** hold a lease too (`DOTRIX_CODING_LEASE_SECONDS`). One whose worker stopped is
  settled from what GitHub shows: its PR is adopted when the push landed, the turn runs again
  when nothing was published, and anything unclear waits for Recover in the Code tab.
- **What a run did** is kept in Postgres as it happens, so a reload, a redeploy of the API, or
  Redis restarting doesn't lose a reply mid-way.

Redis is still needed (the queue, live streams, rate limits); its data can be lost without
losing runs.

## Coding sandboxes on Docker Cloud (recommended)

With `DOTRIX_CODING_SANDBOX=docker-cloud`, Kai's turns run in Docker Cloud sandboxes (the Docker
Agentic Platform) instead of on this VPS. Each turn gets a microVM of its own; the API, worker,
Postgres and Redis stay here. Docker enforces the network policy (only the model API of the turn's
engine is reachable), so the egress proxy isn't needed. The worker still clones and pushes, so no
GitHub token ever reaches a sandbox.

1. **Subscribe** to the Docker Agentic Platform with the Docker account the sandboxes bill to.
2. **A personal access token** for that account with **Allow Cloud Sandboxes access** (`sandbox:use`).
   Put the Docker ID in `DOTRIX_DOCKER_CLOUD_ID` and the token in `DOTRIX_DOCKER_CLOUD_PAT` (Dokploy's
   Environment tab, as a secret).
3. **Publish the coding image** to a registry Docker can pull from. In GitHub: the repository variable
   `CODING_IMAGE` (e.g. `docker.io/acme/dotrix-coding`) and the secrets `DOCKERHUB_USERNAME` and
   `DOCKERHUB_TOKEN`; `.github/workflows/coding-image.yml` then publishes it for each release (or run it
   by hand). Set `DOTRIX_CODING_IMAGE` to the version you deploy, e.g. `docker.io/acme/dotrix-coding:0.1.0`.
4. **Size:** `DOTRIX_CODING_CPUS` picks the sandbox size (Docker pairs 2 GiB of memory with each CPU:
   1, 2, 4, 8 or 16 CPUs); `DOTRIX_CODING_MEMORY` and `DOTRIX_CODING_DOCKER_RUNTIME` don't apply.

The VPS then needs no room for sandboxes: 2 vCPUs and 4 GB run the rest. An account runs 10
sandboxes at once by default; `DOTRIX_CODING_MAX_RUNS` (per worker) stays below that. Docker labels
the API experimental.

**The key stays out of the sandbox.** Each person's model key is stored as a Docker secret for the
session; the sandbox holds a placeholder and Docker writes the real key only into requests to the
model API (`DOTRIX_DOCKER_CLOUD_KEY_INJECTION`, on by default).

**Sessions sleep between turns.** After a turn (and the warm idle time) a session's sandbox is
stopped, keeping its files and installed dependencies, and the next turn wakes it. A sleeping
sandbox is deleted after `DOTRIX_CODING_SLEEP_DAYS` (7); straight away when its session is closed or
deleted, or when someone deletes it ("Delete sandbox" in the session's menu); and the workspace's
oldest when more than `DOTRIX_CODING_SLEEP_MAX` (5) are asleep. The worker sweeps every 10
minutes, and also deletes stopped dotrix sandboxes and secrets nothing refers to (a crash's). An
account stores 50 sandboxes by default, sleeping ones included. A sandbox whose worker crashed stops
itself after the turn time plus the idle time (and 10 minutes), so it stops billing.

**Network.** Owners and admins can let sandboxes reach package registries or other hosts in
Settings → Network. Those apply only to Docker Cloud sandboxes, because there the key stays
out; the other sandbox kinds refuse a turn while any are set.

Not yet checked against a real account (the client is tested against a fake of the documented API,
`tests/unit/test_docker_cloud.py`): whether Docker pulls a private image without extra setup, and how
long a sandbox takes to start.

## Coding sandboxes on the VPS

The worker starts each run's containers on the VPS's Docker. It reaches Docker only through
`docker-proxy` (`tecnativa/docker-socket-proxy`), which allows containers, exec, networks, volumes,
and images, and nothing else. Only the worker and proxy join the internal `docker-control` network;
the API, migrations, and web cannot reach the proxy. The worker also joins the application network
for the database, queue, and storage. The socket itself is never mounted into a dotrix container. Each
run's agent container has no route out except its egress proxy, which reaches only the model API
of the tool Kai runs: Claude Code and Codex by default, or OpenCode on the provider set in
`DOTRIX_CODING_OPENCODE_MODEL` (`DOTRIX_CODING_AGENT=opencode`). Runs use the requester's own key
where the organisation allows it, else the workspace's (Settings → Models), else the server's.

## Outbound access

The API and the worker sit on Docker's default network, so they reach the internet without any
setup. If you put a firewall or an egress proxy in front of the VPS, allow HTTPS (443) to:

| Host | What for |
| --- | --- |
| `api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com`, `api.x.ai`, `api.deepseek.com`, `api.mistral.ai`, `api.groq.com`, `openrouter.ai` | People's model keys: chat, specialists, coding (only the providers people connect) |
| `github.com`, `api.github.com` | Sign-in, the GitHub App, checkouts, pushes and PRs |
| `connect.docker.com`, `hub.docker.com`, and each sandbox's endpoint host | Docker Cloud sandboxes (`docker-cloud`): the Sandboxes API, signing in, and a sandbox's files and commands |
| `api.osv.dev` | `dependency_advisories`: known vulnerabilities in a repository's dependencies. Without it the tool says OSV can't be reached; nothing else breaks |
| `api.sendlyai.com` | Email |
| `api.tavily.com`, and the pages research reads | Web research (optional) |

Building the coding image (`coding-image`) also needs Docker Hub, `registry.npmjs.org`,
`releases.fx.sh`, Debian's package mirrors and Playwright's browser download. The coding sandboxes
themselves need nothing here: their egress proxy reaches only the model API of the run's tool.

To check OSV from the worker:

```bash
docker compose exec worker python -c "import httpx; print(httpx.post('https://api.osv.dev/v1/querybatch', json={'queries': []}, timeout=10).status_code)"
```

`200` means the tool can check dependencies.

**In Dokploy's container list** you'll see each run's two containers (label `dotrix.run=<run id>`)
for as long as it lasts. Leave them to dotrix: stop a run with Stop in dotrix, not in Dokploy.

**Dokploy's cleanup of unused images** can delete `dotrix-coding:latest` while no run uses it; the
next run then fails with "The coding image … isn't built". Leave that cleanup off, or redeploy
after it to rebuild the image.

**If coding runs fail to start through the proxy** (not yet tried on a real Dokploy host: sending
the repository into the sandbox uses `docker exec -i`), run the worker on the VPS itself instead:

```shell
# On the VPS, as a user in the docker group:
git clone https://github.com/<you>/dotrix && cd dotrix
docker build -t dotrix-coding:latest infra/coding
# An env file with the same values as in Dokploy, plus where Postgres and Redis are reachable
# from the host (publish them on 127.0.0.1 in the compose file), and without DOCKER_HOST:
uv sync --frozen --no-dev --package dotrix-backend
uv run python -m dotrix_backend.worker   # or as a systemd service
```

Then remove the `worker` and `docker-proxy` services from the compose file.

## Hardening (recommended before other people's code runs here)

- **gVisor:** install `runsc` on the VPS ([gvisor.dev](https://gvisor.dev/docs/user_guide/install/)),
  register it in `/etc/docker/daemon.json`, restart Docker (this restarts every Dokploy app), then set
  `DOTRIX_CODING_DOCKER_RUNTIME=runsc`. Each sandbox then runs on its own kernel layer.
- **A second VPS for coding:** keeps untrusted code off the machine with your database. Run the
  worker there (as above), pointing at this VPS's Postgres and Redis over a private network.
- **Snapshots:** take one before upgrading; back up the `pgdata` and `miniodata` volumes.
