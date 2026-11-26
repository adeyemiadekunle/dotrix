import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { test } from "node:test";
import { exportJWK, generateKeyPair, SignJWT } from "jose";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "cloudflare:workers") return { url: "data:text/javascript,export class DurableObject {}", shortCircuit: true };
    return nextResolve(specifier, context);
  },
});
const { default: router } = await import("../../deploy/cloudflare/worker.mjs");
const env = {
  DOTRIX_ADMIN_URL: "https://cf-admin-pilot.dotrix.cc",
  DOTRIX_APP_URL: "https://cf-pilot.dotrix.cc",
  DOTRIX_SITE_URL: "https://cf-site-pilot.dotrix.cc",
  DOTRIX_ACCESS_ISSUER: "https://example.cloudflareaccess.com",
  DOTRIX_ACCESS_AUDIENCE: "admin-pilot",
  BACKEND: {
    getByName() {
      return { fetch: (request) => new Response(new URL(request.url).pathname, { headers: { "Set-Cookie": "admin-session=ok" } }) };
    },
  },
  ASSETS: {
    fetch(request) {
      const path = new URL(request.url).pathname;
      const exists = ["/_admin/index.html", "/_site/terms/index.html", "/_web/index.html"].includes(path);
      return new Response(exists ? path : null, { status: exists ? 200 : 404 });
    },
  },
};

test("only the admin origin can reach the admin API and an Access token is required", async () => {
  for (const path of ["/v1/admin/bootstrap", "/v1/%61dmin/bootstrap", "/v1%2Fadmin/bootstrap", "/_admin/index.html"]) {
    assert.equal((await router.fetch(new Request(env.DOTRIX_APP_URL + path), env)).status, 404, path);
  }
  for (const path of ["/", "/v1/admin/bootstrap"]) {
    const response = await router.fetch(new Request(env.DOTRIX_ADMIN_URL + path), env);
    assert.equal(response.status, 403);
    assert.equal(response.headers.get("Cache-Control"), "private, no-store");
  }
  assert.equal((await router.fetch(new Request(env.DOTRIX_ADMIN_URL + "/v1/me"), env)).status, 404);
});

test("Access tokens are verified for the admin application before exposing assets or API responses", async (t) => {
  const { publicKey, privateKey } = await generateKeyPair("RS256");
  const key = { ...(await exportJWK(publicKey)), kid: "fixture", alg: "RS256" };
  t.mock.method(globalThis, "fetch", async (url) => {
    assert.equal(String(url), env.DOTRIX_ACCESS_ISSUER + "/cdn-cgi/access/certs");
    return Response.json({ keys: [key] });
  });
  const signed = async (audience) =>
    new SignJWT({})
      .setProtectedHeader({ alg: "RS256", kid: key.kid })
      .setIssuer(env.DOTRIX_ACCESS_ISSUER)
      .setAudience(audience)
      .setExpirationTime("5m")
      .sign(privateKey);
  const request = (path, token) => new Request(env.DOTRIX_ADMIN_URL + path, { headers: { "Cf-Access-Jwt-Assertion": token } });
  assert.equal((await router.fetch(request("/", await signed("different-app")), env)).status, 403);
  const token = await signed(env.DOTRIX_ACCESS_AUDIENCE);
  const html = await router.fetch(request("/overview", token), env);
  assert.equal(await html.text(), "/_admin/index.html");
  assert.equal(html.headers.get("X-Frame-Options"), "DENY");
  const api = await router.fetch(request("/v1/admin/observe/health", token), env);
  assert.equal(await api.text(), "/v1/admin/observe/health");
  assert.equal(api.headers.get("Set-Cookie"), "admin-session=ok");
});

test("web deep links and marketing pages use their own build", async () => {
  const web = await router.fetch(new Request(env.DOTRIX_APP_URL + "/w/pilot"), env);
  assert.equal(await web.text(), "/_web/index.html");
  const site = await router.fetch(new Request(env.DOTRIX_SITE_URL + "/terms"), env);
  assert.equal(await site.text(), "/_site/terms/index.html");
  assert.equal(site.headers.get("X-Robots-Tag"), "noindex, nofollow");
});
