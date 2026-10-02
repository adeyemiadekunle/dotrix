// Sign in with GitHub, step 1: get GitHub's authorize URL from the backend (which holds the app's
// credentials), keep its `state` and where to go afterwards in a short-lived httpOnly cookie, and
// send the browser to GitHub. With `?link=1` (Settings → Profile) the callback links the GitHub
// account to the person signed in instead of signing in.
import { NextResponse, type NextRequest } from "next/server";

import { API_URL, GITHUB_STATE_COOKIE, backWith, loginWithError, safeNextPath } from "@/lib/session";

export async function GET(request: NextRequest) {
  const next = safeNextPath(request.nextUrl.searchParams.get("next"));
  const link = request.nextUrl.searchParams.get("link") === "1";
  const unavailable = (message: string) =>
    link ? backWith(request, next, { github_error: message }) : loginWithError(request, message, next);
  let start: { authorize_url: string; state: string };
  try {
    const upstream = await fetch(`${API_URL}/v1/auth/oauth/github/start`, { method: "POST", cache: "no-store" });
    if (!upstream.ok) {
      const problem = (await upstream.json().catch(() => null)) as { detail?: string } | null;
      return unavailable(problem?.detail ?? "Sign-in with GitHub isn't available right now.");
    }
    start = (await upstream.json()) as typeof start;
  } catch {
    return unavailable("Sign-in with GitHub isn't available right now.");
  }
  const response = NextResponse.redirect(start.authorize_url);
  response.cookies.set(GITHUB_STATE_COOKIE, JSON.stringify({ state: start.state, next, link }), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    // Lax: sent on GitHub's top-level redirect back to us, never on cross-site subrequests.
    sameSite: "lax",
    path: "/api/auth/github",
    maxAge: 10 * 60,
  });
  return response;
}
