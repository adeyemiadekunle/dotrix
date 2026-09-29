// Sign in with GitHub, step 2: GitHub sends the browser back here with a code. Check the state
// matches the one this browser started with (so nobody can sign you in to their account), let the
// backend trade the code for a session, and put the session into httpOnly cookies.
import { NextResponse, type NextRequest } from "next/server";

import {
  API_URL,
  GITHUB_STATE_COOKIE,
  type TokenPair,
  clientHeaders,
  loginWithError,
  safeNextPath,
  setSession,
} from "@/lib/session";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  let saved: { state?: string; next?: string } = {};
  try {
    saved = JSON.parse(request.cookies.get(GITHUB_STATE_COOKIE)?.value ?? "{}") as typeof saved;
  } catch {
    // A mangled cookie counts as none.
  }
  const next = safeNextPath(saved.next);
  const fail = (message: string) => {
    const response = loginWithError(request, message, next);
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
