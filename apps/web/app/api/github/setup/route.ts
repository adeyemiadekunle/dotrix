// Install the GitHub App, step 2: GitHub's "Setup URL" sends the browser here with the new
// installation's id. Check it's the install this browser started, then sign in with GitHub so the
// backend can confirm this person manages that installation before the workspace uses it
// (/api/auth/github in install mode). An updated installation (repos added or removed) needs
// nothing: back to Settings.
import { type NextRequest } from "next/server";

import { GITHUB_INSTALL_COOKIE, backWith, safeNextPath } from "@/lib/session";

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  let saved: { state?: string; workspace?: string; next?: string } = {};
  try {
    saved = JSON.parse(request.cookies.get(GITHUB_INSTALL_COOKIE)?.value ?? "{}") as typeof saved;
  } catch {
    // A mangled cookie counts as none.
  }
  const next = safeNextPath(saved.next);
  const back = (extra: Record<string, string>) => {
    const response = backWith(request, next, extra);
    response.cookies.delete({ name: GITHUB_INSTALL_COOKIE, path: "/api/github" });
    return response;
  };
  const installationId = Number(params.get("installation_id"));
  if (params.get("setup_action") === "update") return back({ github: "updated" });
  if (!saved.workspace || !saved.state || params.get("state") !== saved.state || !Number.isSafeInteger(installationId) || installationId <= 0) {
    return back({ github_error: "That GitHub install expired or came from another browser. Start it again from Settings." });
  }
  const signIn = new URL("/api/auth/github", request.url);
  signIn.searchParams.set("install", `${saved.workspace}:${installationId}`);
  signIn.searchParams.set("next", next);
  const response = back({});
  response.headers.set("Location", signIn.toString());
  return response;
}
