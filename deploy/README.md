# Deploying dotrix with Dokploy

One VPS running [Dokploy](https://dokploy.com): the web app, the API, the background worker,
Postgres (with pgvector), Redis, and MinIO, and coding runs in sandboxes on the same machine's
Docker. Nobody who uses dotrix installs anything.

```
VPS
└── Docker
    ├── Dokploy, Traefik (TLS, your domain)
    ├── dotrix: web (nginx) → api, worker, migrate (once), postgres, redis, minio, docker-proxy
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
3. **Domain:** add your domain to the `web` service, port 80, with HTTPS. Nothing else needs a
   domain: the API is reached through `web`, on the same origin.
4. **Deploy.** The first deploy builds the three images on the VPS (the backend, the web app, and
   the coding image the worker starts), runs the migrations, then starts everything.

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
