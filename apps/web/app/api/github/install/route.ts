// Install the GitHub App, step 1 (Settings → GitHub): remember which workspace it's for and where
// to come back to in a short httpOnly cookie, then send the browser to GitHub's install page, where
// the person picks an account and its repos. GitHub comes back to /api/github/setup.
import { randomBytes } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";

import { GITHUB_INSTALL_COOKIE, backWith, safeNextPath } from "@/lib/session";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const next = safeNextPath(params.get("next"));
  const workspace = params.get("workspace") ?? "";
  const installUrl = params.get("install_url") ?? "";
  // Only GitHub's own install pages: never an open redirect.
  if (!/^[0-9a-f-]{36}$/i.test(workspace) || !/^https:\/\/github\.com\/apps\/[\w-]+\/installations\/new$/.test(installUrl)) {
    return backWith(request, next, { github_error: "That install link isn't right. Try again from Settings." });
  }
  const state = randomBytes(24).toString("base64url");
  const url = new URL(installUrl);
  url.searchParams.set("state", state);
  const response = NextResponse.redirect(url);
  response.cookies.set(GITHUB_INSTALL_COOKIE, JSON.stringify({ state, workspace, next }), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/api/github",
    maxAge: 30 * 60,
  });
  return response;
}
