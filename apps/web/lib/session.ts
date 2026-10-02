// Server-only session handling (the "backend for frontend").
//
// The browser never sees tokens: the access and refresh tokens live in httpOnly cookies, and
// every API call goes through /api/v1/*, which adds the Authorization header and refreshes the
// access token when it expires.
import "server-only";

import { NextResponse } from "next/server";

export const API_URL = (process.env.PMAGENT_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export const ACCESS_COOKIE = "pm_access";
export const REFRESH_COOKIE = "pm_refresh";

const REFRESH_MAX_AGE = 60 * 60 * 24 * 30; // the backend's refresh tokens last 30 days

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

const secure = process.env.NODE_ENV === "production";

export function setSession(response: NextResponse, tokens: TokenPair): void {
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: tokens.expires_in,
  });
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: REFRESH_MAX_AGE,
  });
}

export function clearSession(response: NextResponse): void {
  response.cookies.delete(ACCESS_COOKIE);
  response.cookies.delete(REFRESH_COOKIE);
}

// The backend rotates refresh tokens and treats a reused one as theft (it signs the session out).
// A page fires several API calls at once, so when the access token expires they'd all try to
// refresh with the same token. Share one refresh per token, and remember its result briefly so
// requests that were already in flight with the old cookie get the new pair too.
const refreshes = new Map<string, Promise<TokenPair | null>>();
const REMEMBER_MS = 30_000;

/** Trade a refresh token for a new pair (the backend rotates it), or null if it's no longer valid. */
export function refreshTokens(refreshToken: string, client: Record<string, string> = {}): Promise<TokenPair | null> {
  let pending = refreshes.get(refreshToken);
  if (!pending) {
    pending = fetch(`${API_URL}/v1/auth/refresh`, {
      method: "POST",
      // Who's refreshing (`clientHeaders`), so the session keeps the browser's address, not ours.
      headers: { "Content-Type": "application/json", ...client },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    })
      .then(async (res) => (res.ok ? ((await res.json()) as TokenPair) : null))
      .catch(() => null);
    refreshes.set(refreshToken, pending);
    setTimeout(() => refreshes.delete(refreshToken), REMEMBER_MS);
  }
  return pending;
}

/** Pass a backend error (problem+json) through unchanged. */
export function passError(upstream: Response): Response {
  const headers = new Headers({ "Content-Type": upstream.headers.get("content-type") ?? "application/problem+json" });
  const retryAfter = upstream.headers.get("retry-after");
  if (retryAfter) headers.set("Retry-After", retryAfter);
  return new Response(upstream.body, { status: upstream.status, headers });
}

/** Who's calling, for the backend's per-IP rate limits and for its list of signed-in browsers
 * and apps (Settings → Devices): every request reaches it from this server, so it believes
 * X-Forwarded-For only from here (its PMAGENT_TRUSTED_PROXIES). Next fills the header from the
 * socket only when it's missing, so in production put a proxy in front that appends the real
 * address (nginx, the host's load balancer); per-email limits don't depend on it. The browser's
 * (or the desktop app's) User-Agent says what signed in: "Chrome on macOS", "Desktop app". */
export function clientHeaders(request: Request): Record<string, string> {
  const headers: Record<string, string> = {};
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) headers["X-Forwarded-For"] = forwarded;
  const userAgent = request.headers.get("user-agent");
  if (userAgent) headers["User-Agent"] = userAgent;
  return headers;
}

/** The state and destination of a GitHub sign-in in progress (see app/api/auth/github). */
export const GITHUB_STATE_COOKIE = "pm_github_state";
/** Installing the GitHub App: which workspace it's for, and where to come back to. */
export const GITHUB_INSTALL_COOKIE = "pm_github_install";

/** A same-site path to go to after signing in, or "/" (never another site). */
export function safeNextPath(next: string | null | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

/** Back to the sign-in page with a message to show. */
export function loginWithError(request: Request, message: string, next: string): NextResponse {
  const login = new URL("/login", request.url);
  login.searchParams.set("error", message);
  if (next !== "/") login.searchParams.set("next", next);
  return NextResponse.redirect(login);
}

/** Back to a page of the app with a message for it in the query (`?github=linked`). */
export function backWith(request: Request, next: string, params: Record<string, string>): NextResponse {
  const url = new URL(next, request.url);
  for (const [name, value] of Object.entries(params)) url.searchParams.set(name, value);
  return NextResponse.redirect(url);
}

/** Which other ways to sign in the backend has set up (none if it can't be reached). */
export async function authProviders(): Promise<{ github: boolean }> {
  try {
    const res = await fetch(`${API_URL}/v1/auth/providers`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as { github: boolean }) : { github: false };
  } catch {
    return { github: false };
  }
}
