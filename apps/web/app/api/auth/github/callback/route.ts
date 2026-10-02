// Sign in with GitHub, step 2: GitHub sends the browser back here with a code. Check the state
// matches the one this browser started with (so nobody can sign you in to their account), let the
// backend trade the code for a session, and put the session into httpOnly cookies. Started from
// Settings (`link`), the code links the GitHub account to the person signed in instead.
import { NextResponse, type NextRequest } from "next/server";

import {
  ACCESS_COOKIE,
  API_URL,
  GITHUB_STATE_COOKIE,
  REFRESH_COOKIE,
  type TokenPair,
  backWith,
  clientHeaders,
  loginWithError,
  refreshTokens,
  safeNextPath,
  setSession,
} from "@/lib/session";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  let saved: { state?: string; next?: string; link?: boolean } = {};
  try {
    saved = JSON.parse(request.cookies.get(GITHUB_STATE_COOKIE)?.value ?? "{}") as typeof saved;
  } catch {
    // A mangled cookie counts as none.
  }
  const next = safeNextPath(saved.next);
  const fail = (message: string) => {
    const response = saved.link ? backWith(request, next, { github_error: message }) : loginWithError(request, message, next);
    response.cookies.delete({ name: GITHUB_STATE_COOKIE, path: "/api/auth/github" });
    return response;
  };

  if (params.get("error")) {
    return fail(params.get("error") === "access_denied" ? "GitHub sign-in was cancelled." : "GitHub sign-in didn't work. Try again.");
  }
  const code = params.get("code");
  if (!code || !saved.state || params.get("state") !== saved.state) {
    return fail("That GitHub sign-in expired or came from another browser. Try again.");
  }

  if (saved.link) return link(request, code, next, fail);

  const upstream = await fetch(`${API_URL}/v1/auth/oauth/github/finish`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...clientHeaders(request) },
    body: JSON.stringify({ code }),
    cache: "no-store",
  }).catch(() => null);
  if (!upstream?.ok) {
    const problem = (await upstream?.json().catch(() => null)) as { detail?: string } | null;
    return fail(problem?.detail ?? "GitHub sign-in didn't work. Try again.");
  }
  const response = NextResponse.redirect(new URL(next, request.url));
  response.cookies.delete({ name: GITHUB_STATE_COOKIE, path: "/api/auth/github" });
  setSession(response, (await upstream.json()) as TokenPair);
  return response;
}

/** Link the GitHub account to the person signed in (their session cookies), then back to Settings. */
async function link(request: NextRequest, code: string, next: string, fail: (message: string) => NextResponse) {
  const send = (token: string | undefined) =>
    fetch(`${API_URL}/v1/me/sign-in-methods/github`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ code }),
      cache: "no-store",
    }).catch(() => null);
  let upstream = await send(request.cookies.get(ACCESS_COOKIE)?.value);
  let refreshed: TokenPair | null = null;
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (upstream?.status === 401 && refreshToken) {
    // The API checks who you are before it uses the code, so after a refresh it can be sent again.
    refreshed = await refreshTokens(refreshToken, clientHeaders(request));
    if (refreshed) upstream = await send(refreshed.access_token);
  }
  let response: NextResponse;
  if (upstream?.ok) {
    response = backWith(request, next, { github: "linked" });
    response.cookies.delete({ name: GITHUB_STATE_COOKIE, path: "/api/auth/github" });
  } else {
    const problem = (await upstream?.json().catch(() => null)) as { detail?: string } | null;
    response = fail(problem?.detail ?? "Linking GitHub didn't work. Try again.");
  }
  if (refreshed) setSession(response, refreshed);
  return response;
}
