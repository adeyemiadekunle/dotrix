import { DurableObject } from "cloudflare:workers";

const PORT = 8000;
const IDLE_MS = 5 * 60 * 1000;
const STARTUP_MS = 45_000;
const REQUIRED_SECRETS = [
  "DOTRIX_DATABASE_URL",
  "DOTRIX_REDIS_URL",
  "DOTRIX_REDIS_CA_PEM",
  "DOTRIX_JWT_SECRET",
  "DOTRIX_ENCRYPTION_KEY",
  "DOTRIX_S3_ENDPOINT_URL",
  "DOTRIX_S3_ACCESS_KEY",
  "DOTRIX_S3_SECRET_KEY",
  "DOTRIX_S3_BUCKET",
  "DOTRIX_SENDLY_API_KEY",
  "DOTRIX_EMAIL_FROM",
];

function containerEnv(env) {
  const secrets = {};
  for (const name of REQUIRED_SECRETS) {
    if (!env[name]) throw new Error(`Missing staging binding: ${name}`);
    secrets[name] = env[name];
  }
  if (!secrets.DOTRIX_REDIS_URL.startsWith("rediss://")) throw new Error("Staging Redis requires TLS");
  return {
    ...secrets,
    DOTRIX_ENV: "staging",
    DOTRIX_APP_URL: env.DOTRIX_APP_URL,
    DOTRIX_CORS_ORIGINS: JSON.stringify([env.DOTRIX_APP_URL]),
    DOTRIX_JOBS: "worker",
    DOTRIX_RATE_LIMITS: "redis",
    DOTRIX_CODING_SANDBOX: "off",
    DOTRIX_EMAIL_BACKEND: "sendly",
    DOTRIX_S3_REGION: "auto",
    // The private container port is reachable through this Worker, which rewrites proxy headers.
    FORWARDED_ALLOW_IPS: "*",
  };
}

export class DotrixApi extends DurableObject {
  ready = false;
  starting;

  async fetch(request) {
    const container = this.ctx.container;
    if (!this.ready || !container.running) {
      this.ready = false;
      this.starting ??= this.startAndWait(container).finally(() => {
        this.starting = undefined;
      });
      try {
        await this.starting;
        this.ready = true;
      } catch {
        console.error("Staging API failed to become ready");
        return new Response("Staging API is unavailable", { status: 503, headers: { "Retry-After": "5" } });
      }
    }

    const url = new URL(request.url);
    url.protocol = "http:";
    url.host = "container";
    const forwarded = new Request(url, request);
    const { headers } = forwarded;
    const clientIp = headers.get("CF-Connecting-IP");
    headers.set("Host", new URL(this.env.DOTRIX_APP_URL).host);
    headers.delete("Forwarded");
    headers.delete("X-Forwarded-For");
    headers.delete("X-Forwarded-Host");
    headers.delete("X-Forwarded-Port");
    headers.set("X-Forwarded-Proto", "https");
    if (clientIp) headers.set("X-Forwarded-For", clientIp);
    return container.getTcpPort(PORT).fetch(forwarded, { redirect: "manual" });
  }

  async startAndWait(container) {
    if (!container.running) {
      container.start({
        image: container.images.base,
        instance: { vcpu: 0.5, memoryMib: 1024, diskMb: 4000 },
        enableInternet: true,
        env: containerEnv(this.env),
      });
    }
    await container.setInactivityTimeout(IDLE_MS);
    const port = container.getTcpPort(PORT);
    const deadline = Date.now() + STARTUP_MS;
    while (Date.now() < deadline) {
      try {
        const response = await port.fetch("http://container/health", { signal: AbortSignal.timeout(1000) });
        await response.body?.cancel();
        if (response.ok) return;
      } catch {
        // The API has not opened its port yet.
      }
      await globalThis.scheduler.wait(250);
    }
    throw new Error("Staging API startup timed out");
  }
}

export default {
  fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (["/v1", "/api", "/health"].some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"))) {
      return env.BACKEND.getByName("staging").fetch(request);
    }
    return env.ASSETS.fetch(request);
  },
};
