// Forwards /api/v1/* to the backend's /v1/*, adding the access token from the session cookie.
// On a 401 it refreshes the session once and retries, so pages never handle token expiry.
import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import {
  ACCESS_COOKIE,
  API_URL,
  REFRESH_COOKIE,
  type TokenPair,
  clearSession,
  refreshTokens,
  setSession,
} from "@/lib/session";

// Request headers passed through to the backend; everything else (cookies included) stays here.
const FORWARD = ["accept", "content-type", "if-none-match", "x-request-id"];
// Response headers passed back to the browser.
const RETURN = ["content-type", "content-disposition", "etag", "location", "x-request-id", "cache-control"];

async function handle(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = `${API_URL}/v1/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();
  const jar = await cookies();

  const send = (token: string | undefined) => {
    const headers = new Headers();
    for (const name of FORWARD) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(url, { method: request.method, headers, body, cache: "no-store", redirect: "manual" });
  };

  let upstream: Response;
  let refreshed: TokenPair | null = null;
  const refreshToken = jar.get(REFRESH_COOKIE)?.value;
  try {
    upstream = await send(jar.get(ACCESS_COOKIE)?.value);
    if (upstream.status === 401 && refreshToken) {
      refreshed = await refreshTokens(refreshToken);
      if (refreshed) upstream = await send(refreshed.access_token);
    }
  } catch {
    // The API is down or restarting: say so, in the same shape as every other error.
    return NextResponse.json(
      { type: "about:blank", title: "Bad Gateway", status: 502, detail: "The pmagent API isn't reachable right now." },
      { status: 502, headers: { "Content-Type": "application/problem+json" } },
    );
  }

  const headers = new Headers();
  for (const name of RETURN) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  const response = new NextResponse(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers,
  });
  if (refreshed) setSession(response, refreshed);
  else if (upstream.status === 401 && refreshToken) clearSession(response); // the session is over
  return response;
}

export { handle as DELETE, handle as GET, handle as PATCH, handle as POST, handle as PUT };
