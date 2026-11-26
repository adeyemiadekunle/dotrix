import { DurableObject } from "cloudflare:workers";
import { createRemoteJWKSet, jwtVerify } from "jose";

const PORT = 8000;
const IDLE_MS = 5 * 60 * 1000;
const STARTUP_MS = 45_000;
const accessKeys = new Map();
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
  "DOTRIX_CLOUDFLARE_EMAIL_ACCOUNT_ID",
  "DOTRIX_CLOUDFLARE_EMAIL_API_TOKEN",
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
    DOTRIX_ADMIN_URL: env.DOTRIX_ADMIN_URL,
    DOTRIX_ADMIN_BOOTSTRAP_TOKEN: env.DOTRIX_ADMIN_BOOTSTRAP_TOKEN ?? "",
    DOTRIX_DEPLOYMENT_REVISION: env.DOTRIX_DEPLOYMENT_REVISION,
    DOTRIX_CORS_ORIGINS: JSON.stringify([env.DOTRIX_APP_URL, env.DOTRIX_ADMIN_URL]),
    DOTRIX_JOBS: "worker",
    DOTRIX_RATE_LIMITS: "redis",
    DOTRIX_CODING_SANDBOX: "off",
    DOTRIX_EMAIL_BACKEND: "cloudflare",
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
    headers.set("Host", new URL(request.url).host);
    headers.delete("Forwarded");
    headers.delete("X-Forwarded-For");
    headers.delete("X-Forwarded-Host");
    headers.delete("X-Forwarded-Port");
    headers.delete("Cf-Access-Jwt-Assertion");
    const cookies = (headers.get("Cookie") ?? "").split(";").filter((cookie) => !/^\s*CF_Authorization=/.test(cookie));
    if (cookies.join("").trim()) headers.set("Cookie", cookies.join(";"));
    else headers.delete("Cookie");
    headers.set("X-Forwarded-Proto", "https");
    if (clientIp) headers.set("X-Forwarded-For", clientIp);
    return container.getTcpPort(PORT).fetch(forwarded, { redirect: "manual" });
  }

  async startAndWait(container) {
    const cold = !container.running;
    const started = Date.now();
    if (cold) {
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
        if (response.ok) {
          if (cold) console.info({ event: "dotrix_api_cold_start", duration_ms: Date.now() - started, revision: this.env.DOTRIX_DEPLOYMENT_REVISION });
          return;
        }
      } catch {
        // The API has not opened its port yet.
      }
      await globalThis.scheduler.wait(250);
    }
    throw new Error("Staging API startup timed out");
  }
}

function under(path, prefix) {
  return path === prefix || path.startsWith(prefix + "/");
}

async function hasAdminAccess(request, env) {
  const issuer = env.DOTRIX_ACCESS_ISSUER;
  const audience = env.DOTRIX_ACCESS_AUDIENCE;
  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!token || !audience || !/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(issuer ?? "")) return false;
  try {
    let keys = accessKeys.get(issuer);
    if (!keys) {
      keys = createRemoteJWKSet(new URL("/cdn-cgi/access/certs", issuer), { timeoutDuration: 3000 });
      accessKeys.set(issuer, keys);
    }
    await jwtVerify(token, keys, { issuer, audience, algorithms: ["RS256"], requiredClaims: ["exp"] });
    return true;
  } catch {
    return false;
  }
}

async function assets(request, env, app, index = null) {
  if (request.method !== "GET" && request.method !== "HEAD") return new Response(null, { status: 405 });
  const url = new URL(request.url);
  url.pathname = `/_${app}${url.pathname}`;
  const response = await env.ASSETS.fetch(new Request(url, { method: request.method, headers: request.headers }));
  if (response.status !== 404 || !index) return response;
  await response.body?.cancel();
  url.pathname = `/_${app}${index}`;
  const headers = new Headers(request.headers);
  headers.delete("If-None-Match");
  headers.delete("If-Modified-Since");
  return env.ASSETS.fetch(new Request(url, { method: request.method, headers }));
}

function protect(response, admin) {
  const secured = new Response(response.body, response);
  secured.headers.set("X-Robots-Tag", "noindex, nofollow");
  if (admin) {
    secured.headers.set("Cache-Control", "private, no-store");
    secured.headers.set("Content-Security-Policy", "frame-ancestors 'none'");
    secured.headers.set("X-Frame-Options", "DENY");
    secured.headers.set("X-Content-Type-Options", "nosniff");
    secured.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  }
  return secured;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let path;
    try {
      path = decodeURIComponent(url.pathname);
    } catch {
      return new Response(null, { status: 400 });
    }
    const isAdmin = url.origin === env.DOTRIX_ADMIN_URL;
    const isWeb = url.origin === env.DOTRIX_APP_URL;
    const isSite = url.origin === env.DOTRIX_SITE_URL;
    const adminApi = under(path, "/v1/admin");
    const api = ["/v1", "/api", "/health"].some((prefix) => under(path, prefix));
    if ((!isAdmin && adminApi) || (!isAdmin && !isWeb && !isSite) || (api && !isWeb && !adminApi)) {
      return new Response(null, { status: 404 });
    }
    if (isAdmin && !(await hasAdminAccess(request, env))) {
      return protect(new Response("Cloudflare Access required", { status: 403 }), true);
    }
    if (api) {
      const response = await env.BACKEND.getByName("staging").fetch(request);
      return isAdmin ? protect(response, true) : response;
    }
    const app = isAdmin ? "admin" : isWeb ? "web" : "site";
    const route = path.replace(/\/$/, "");
    const siteIndex = ["", "/terms", "/privacy"].includes(route) ? `${route}/index.html` : null;
    const index = isSite ? siteIndex : !under(path, "/assets") && !/\.[^/]+$/.test(path) ? "/index.html" : null;
    return protect(await assets(request, env, app, index), isAdmin);
  },
};
