// Server-only session handling (the "backend for frontend").
//
// The browser never sees tokens: the access and refresh tokens live in httpOnly cookies, and
// every API call goes through /api/v1/*, which adds the Authorization header and refreshes the
// access token when it expires.
import "server-only";

import type { NextResponse } from "next/server";

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
export function refreshTokens(refreshToken: string): Promise<TokenPair | null> {
  let pending = refreshes.get(refreshToken);
  if (!pending) {
    pending = fetch(`${API_URL}/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/problem+json" },
  });
}
