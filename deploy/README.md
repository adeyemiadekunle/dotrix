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

A third run waits ("Waiting for a free sandbox") until one finishes. A warm session keeps its
sandbox between turns (`DOTRIX_CODING_WARM_MAX`, `DOTRIX_CODING_IDLE_MINUTES`); an idle one uses
little memory, but keep it low on one machine.

## Set up

1. **Dokploy:** create a project, then a **Docker Compose** service from this repository, with the
   compose path `deploy/docker-compose.dokploy.yml`.
2. **Environment:** paste `deploy/dokploy.env.example` into the service's Environment tab and fill
   it in. The GitHub App's callback and webhook URLs use your `DOTRIX_APP_URL`.
3. **Domain:** add your domain to the `web` service, port 80, with HTTPS. Nothing else needs a
   domain: the API is reached through `web`, on the same origin.
4. **Deploy.** The first deploy builds the three images on the VPS (the backend, the web app, and
   the coding image the worker starts), runs the migrations, then starts everything.

## Coding sandboxes on the VPS

The worker starts each run's containers on the VPS's Docker. It reaches Docker only through
`docker-proxy` (`tecnativa/docker-socket-proxy`), which allows containers, exec, networks, volumes,
and images, and nothing else; the socket itself is never mounted into a dotrix container. Each
run's agent container has no route out except its egress proxy, which reaches only the model API.

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
