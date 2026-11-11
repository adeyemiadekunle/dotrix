// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../../lib/api";
import { directoryFailed } from "../shell/StoreBridge";

const assign = vi.fn();
const json = (status: number) => new Response("{}", { status });

beforeEach(() => {
  localStorage.clear();
  assign.mockReset();
  vi.stubGlobal("location", { pathname: "/w/x", search: "", assign });
});
afterEach(() => vi.unstubAllGlobals());

function stub(handler: (url: string) => Response | Promise<Response>) {
  const fn = vi.fn((input: RequestInfo | URL) => Promise.resolve(handler(input instanceof Request ? input.url : String(input))));
  vi.stubGlobal("fetch", fn);
  return fn;
}
const refreshCalls = (fn: ReturnType<typeof stub>) =>
  fn.mock.calls.filter(([input]) => String(input instanceof Request ? input.url : input).includes("/api/auth/refresh")).length;

describe("apiFetch session refresh", () => {
  it("retries after a successful refresh", async () => {
    let first = true;
    stub((url) => {
      if (url.includes("/api/auth/refresh")) return json(200);
      if (first) {
        first = false;
        return json(401);
      }
      return json(200);
    });
    expect((await apiFetch("http://localhost/v1/me")).status).toBe(200);
    expect(assign).not.toHaveBeenCalled();
  });

  it("signs out when the refresh is refused", async () => {
    stub((url) => (url.includes("/api/auth/refresh") ? json(401) : json(401)));
    await apiFetch("http://localhost/v1/me");
    expect(assign).toHaveBeenCalledOnce();
  });

  it("stays signed in when the refresh is unavailable", async () => {
    stub((url) => (url.includes("/api/auth/refresh") ? json(503) : json(401)));
    expect((await apiFetch("http://localhost/v1/me")).status).toBe(401);
    expect(assign).not.toHaveBeenCalled();
  });

  it("stays signed in when the refresh fails to connect", async () => {
    const fn = vi.fn((input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      return url.includes("/api/auth/refresh") ? Promise.reject(new TypeError("offline")) : Promise.resolve(json(401));
    });
    vi.stubGlobal("fetch", fn);
    expect((await apiFetch("http://localhost/v1/me")).status).toBe(401);
    expect(assign).not.toHaveBeenCalled();
  });

  it("shares one refresh between simultaneous 401s without Web Locks", async () => {
    vi.stubGlobal("navigator", {});
    const seen = new Set<string>();
    const fn = stub((url) => {
      if (url.includes("/api/auth/refresh")) return json(200);
      if (!seen.has(url)) {
        seen.add(url);
        return json(401);
      }
      return json(200);
    });
    const results = await Promise.all([1, 2, 3, 4, 5].map((i) => apiFetch(`http://localhost/v1/item/${i}`)));
    expect(results.map((r) => r.status)).toEqual([200, 200, 200, 200, 200]);
    expect(refreshCalls(fn)).toBe(1);
  });
});

describe("directoryFailed", () => {
  it("is true only for an error without data", () => {
    expect(directoryFailed([{ status: "error", data: undefined }])).toBe(true);
    expect(directoryFailed([{ status: "error", data: [] }])).toBe(false);
    expect(directoryFailed([{ status: "pending", data: undefined }, undefined])).toBe(false);
  });
});
