// Settings and Members against the API, for a real workspace (live.ts loads the rest). Your
// account (profile, sign-in methods, password, notifications, where you're signed in), the
// workspace (name, what members can do, turning a personal one into an organisation), its people
// (invites, removing, handing over ownership, who sees a restricted project), and the agents'
// settings (contracts, rules, skills, GitHub). Sections load what they show when they open
// (useApi); the seeded demo keeps its own behaviour.
import { useEffect, useState } from "react";

import { api, unwrap, type Schemas } from "@/lib/api";

import { toast } from "../ui/toast";
import { isLive, live, loadWorkspace } from "./live";
import { D, render } from "./store";
import type { Member } from "./types";

const wsPath = () => ({ params: { path: { workspace_id: live.ws!.id } } });
const said = (e: unknown) => (e instanceof Error ? e.message : "");
function failed(what: string, e: unknown) {
  toast(`${what} didn't save${said(e) ? `: ${said(e)}` : ""}`, { kind: "err", ms: 6000 });
}

/** What an API section shows: loaded when it opens (and again with `reload`), only in a real workspace. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []): { data: T | undefined; error: string; reload: () => void } {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!isLive()) return;
    let on = true;
    load()
      .then((d) => on && (setData(d), setError("")))
      .catch((e: unknown) => on && setError(said(e) || "It didn't load"));
    return () => {
      on = false;
    };
  }, [n, live.ws?.id, ...deps]);
  return { data, error, reload: () => setN((x) => x + 1) };
}

/* ---------- your account ---------- */

export const getMe = () => unwrap(api.GET("/v1/me"));

export async function profileSaved(name: string, title: string) {
  await unwrap(api.PATCH("/v1/me", { body: { display_name: name, title } }));
}

export const signInMethods = () => unwrap(api.GET("/v1/me/sign-in-methods"));
export const unlinkGitHub = () => unwrap(api.DELETE("/v1/me/sign-in-methods/{provider}", { params: { path: { provider: "github" } } }));
/** GitHub links through a top-level redirect; it comes back here. */
export function linkGitHub() {
  location.assign(`/api/auth/github?link=1&next=${encodeURIComponent(location.pathname)}`);
}

export const passwordChanged = (current: string | null, next: string) => unwrap(api.PUT("/v1/me/password", { body: { current_password: current, new_password: next } }));
export async function passwordResetRequested(email: string) {
  await unwrap(api.POST("/v1/auth/password-reset/request", { body: { email } }));
}

export type NotifSettings = Schemas["NotificationSettings"];
export const notifSettings = () => unwrap(api.GET("/v1/me/notification-settings"));
export const notifSettingsSaved = (s: NotifSettings) => unwrap(api.PUT("/v1/me/notification-settings", { body: s }));

export const sessions = () => unwrap(api.GET("/v1/me/sessions"));
export const sessionSignedOut = (id: string) => unwrap(api.DELETE("/v1/me/sessions/{session_id}", { params: { path: { session_id: id } } }));
export const otherSessionsSignedOut = () => unwrap(api.POST("/v1/me/sessions/sign-out-others"));

export const tokens = () => unwrap(api.GET("/v1/me/tokens"));
export const tokenCreated = (name: string, days: number | null) => unwrap(api.POST("/v1/me/tokens", { body: { name, scopes: ["read", "write"], expires_in_days: days } }));
export const tokenRevoked = (id: string) => unwrap(api.DELETE("/v1/me/tokens/{token_id}", { params: { path: { token_id: id } } }));

/* ---------- the workspace ---------- */

/** Rename the workspace (the store shows the new name already). */
export async function workspaceRenamed(name: string) {
  const w = await unwrap(api.PATCH("/v1/workspaces/{workspace_id}", { ...wsPath(), body: { name } }));
  live.ws = { ...live.ws!, name: w.name };
  const listed = D().workspaces.find((x) => x.id === w.id);
  if (listed) listed.name = w.name;
  render();
}

/** What a workspace grants its members on top of their role (owners and admins set it). */
export const GRANTABLE: [Schemas["Permission"], string, string][] = [
  ["knowledge:write", "Edit documents", "Change the project's knowledge directly."],
  ["agents:approve", "Approve agents' changes", "Approve or reject what an agent proposes."],
  ["agents:code", "Start coding", "Ask Claude Code or Codex to work on a task."],
  ["agents:choose_model", "Choose the agents' model", "Bigger models cost more."],
];
export async function memberPermissionsSaved(perms: Schemas["Permission"][]) {
  const was = live.ws!.member_permissions ?? [];
  live.ws = { ...live.ws!, member_permissions: perms };
  render();
  try {
    const w = await unwrap(api.PATCH("/v1/workspaces/{workspace_id}", { ...wsPath(), body: { member_permissions: perms } }));
    live.ws = { ...live.ws!, member_permissions: w.member_permissions };
  } catch (e) {
    live.ws = { ...live.ws!, member_permissions: was };
    failed("What members can do", e);
  }
  render();
}

/** Pause (owners and admins) or resume (owners) every agent's changes without approval. */
export async function unattendedPaused(on: boolean) {
  const was = !!live.ws!.unattended_paused;
  live.ws = { ...live.ws!, unattended_paused: on };
  render();
  try {
    const w = await unwrap(api.PATCH("/v1/workspaces/{workspace_id}", { ...wsPath(), body: { unattended_paused: on } }));
    live.ws = { ...live.ws!, unattended_paused: w.unattended_paused };
    toast(on ? "Agents ask before every change" : "Agents' standing rules are back on");
  } catch (e) {
    live.ws = { ...live.ws!, unattended_paused: was };
    failed("Pausing changes without approval", e);
  }
  render();
}

/** A personal workspace becomes an organisation (you get a new, empty personal one); reloaded. */
export async function convertedToOrganization(name: string | null) {
  const w = await unwrap(api.POST("/v1/workspaces/{workspace_id}/convert-to-organization", { ...wsPath(), body: { name } }));
  await loadWorkspace(w.slug);
  return w;
}

/* ---------- people ---------- */

const INVITE_ID = "invite:";
export const isInvite = (id: string) => id.startsWith(INVITE_ID);
const nameFromEmail = (e: string) =>
  e
    .split("@")[0]!
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
const ROLE_IN: Record<string, Member["role"]> = { owner: "Owner", admin: "Admin", member: "Member", guest: "Guest" };

function toInvited(i: Schemas["InviteRead"]): Member {
  const email = i.email ?? "";
  return { id: INVITE_ID + i.id, name: nameFromEmail(email), email, role: ROLE_IN[i.role] ?? "Member", team: "", title: "", c: "#6B7280", status: "invited", last: null, tz: "" };
}

/** Pending email invites, shown with the members as "Invite pending" (owners and admins see them). */
export async function loadInvites() {
  if (!isLive() || live.ws!.kind !== "organization") return;
  try {
    const invites = await unwrap(api.GET("/v1/workspaces/{workspace_id}/invites", wsPath()));
    const pending = invites.filter((i) => i.kind === "email" && i.email).map(toInvited);
    D().members = [...D().members.filter((m) => !isInvite(m.id)), ...pending];
    render();
  } catch {
    /* members only: no invites to show */
  }
}

/** Invite people by email; each one sent is listed as pending. Returns how many were sent. */
export async function invitesSent(emails: string[], role: Member["role"]): Promise<number> {
  let sent = 0;
  for (const email of emails) {
    try {
      const i = await unwrap(api.POST("/v1/workspaces/{workspace_id}/invites", { ...wsPath(), body: { email, role: role.toLowerCase() as Schemas["EmailInviteCreate"]["role"] } }));
      D().members = [...D().members.filter((m) => m.email.toLowerCase() !== email.toLowerCase() || !isInvite(m.id)), toInvited(i)];
      sent++;
    } catch (e) {
      failed(`The invite to ${email}`, e);
    }
  }
  render();
  return sent;
}

/** A link anyone can join with, for a week (until revoked). */
export async function inviteLinkCreated(role: Member["role"]): Promise<string> {
  // A link brings people in as members or guests; admins are invited by email.
  const r = role === "Guest" ? "guest" : "member";
  const l = await unwrap(api.POST("/v1/workspaces/{workspace_id}/invites/links", { ...wsPath(), body: { role: r, max_uses: null, expires_in_days: 7 } }));
  return l.url;
}

export async function inviteRevoked(m: Member) {
  await unwrap(api.DELETE("/v1/workspaces/{workspace_id}/invites/{invite_id}", { params: { path: { workspace_id: live.ws!.id, invite_id: m.id.slice(INVITE_ID.length) } } }));
  D().members = D().members.filter((x) => x.id !== m.id);
  render();
}

/** Resending is a new invite (a new link by email) in place of the old one. */
export async function inviteResent(m: Member) {
  await inviteRevoked(m);
  await invitesSent([m.email], m.role);
}

/** Take someone out of the workspace (the API unassigns their issues). */
export async function memberRemoved(m: Member) {
  if (isInvite(m.id)) return inviteRevoked(m);
  await unwrap(api.DELETE("/v1/workspaces/{workspace_id}/members/{user_id}", { params: { path: { workspace_id: live.ws!.id, user_id: m.id } } }));
}

/** Hand the workspace to another member; you become an admin. */
export async function ownershipTransferred(m: Member) {
  await unwrap(api.POST("/v1/workspaces/{workspace_id}/transfer-ownership", { ...wsPath(), body: { user_id: m.id } }));
  await loadWorkspace(live.slug!);
}

/** Who sees a project, and why (everyone, their role, or added to a restricted one). */
export const projectMembers = (pid: string) => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/members", { params: { path: { workspace_id: live.ws!.id, project_id: pid } } }));
export async function projectMemberSet(pid: string, userId: string, on: boolean) {
  const params = { params: { path: { workspace_id: live.ws!.id, project_id: pid, user_id: userId } } };
  await unwrap(on ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/members/{user_id}", params) : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/members/{user_id}", params));
}

/* ---------- agents ---------- */

/** The API's handle for one the store names "auto". */
export const apiHandle = (h: string) => (h === "auto" ? "project-manager" : h);
export const agentDetail = (handle: string) => unwrap(api.GET("/v1/workspaces/{workspace_id}/agents/{handle}", { params: { path: { workspace_id: live.ws!.id, handle: apiHandle(handle) } } }));
export const agentCatalog = () => unwrap(api.GET("/v1/workspaces/{workspace_id}/agents/catalog", wsPath()));
export const models = () => unwrap(api.GET("/v1/workspaces/{workspace_id}/models", wsPath()));

export type AgentFields = Schemas["AgentFields"];
/** The fields of a contract as saved (everything an AgentRead carries that a save takes). */
export function fieldsOf(a: Schemas["AgentRead"]): AgentFields {
  const { name, description, instructions, model, budget_tokens, tools, access, issue_types, can_call, autonomy, output, pipeline, triggers } = a;
  return { name, description, instructions, model, budget_tokens, tools, access, issue_types, can_call, autonomy, output, pipeline, triggers };
}
export const agentSaved = (handle: string, agent: AgentFields, base: number | null, note = "") =>
  unwrap(api.PUT("/v1/workspaces/{workspace_id}/agents/{handle}", { params: { path: { workspace_id: live.ws!.id, handle: apiHandle(handle) } }, body: { agent, note, base_version: base } }));
/** A built-in back to its default, or a custom agent removed. */
export const agentReset = (handle: string) => unwrap(api.DELETE("/v1/workspaces/{workspace_id}/agents/{handle}", { params: { path: { workspace_id: live.ws!.id, handle: apiHandle(handle) } } }));

export const rules = () => unwrap(api.GET("/v1/workspaces/{workspace_id}/rules", wsPath()));
export const ruleSaved = (handle: string, content: string, base: number) => unwrap(api.PUT("/v1/workspaces/{workspace_id}/rules/{handle}", { params: { path: { workspace_id: live.ws!.id, handle } }, body: { content, base_version: base } }));
export const skills = () => unwrap(api.GET("/v1/workspaces/{workspace_id}/skills", wsPath()));
export const skillSaved = (name: string, content: string, base: number) => unwrap(api.PUT("/v1/workspaces/{workspace_id}/skills/{name}", { params: { path: { workspace_id: live.ws!.id, name } }, body: { content, base_version: base } }));

/* ---------- GitHub ---------- */

export const githubStatus = () => unwrap(api.GET("/v1/workspaces/{workspace_id}/github", wsPath()));
export const githubRepos = () => unwrap(api.GET("/v1/workspaces/{workspace_id}/github/repos", wsPath()));
export const installationRemoved = (ref: string) => unwrap(api.DELETE("/v1/workspaces/{workspace_id}/github/installations/{installation_ref}", { params: { path: { workspace_id: live.ws!.id, installation_ref: ref } } }));
export function installGitHub(status: Schemas["GitHubStatus"]) {
  if (!status.install_url) return;
  const params = new URLSearchParams({ workspace: live.ws!.id, install_url: status.install_url, next: location.pathname });
  location.assign(`/api/github/install?${params}`);
}
export async function repoConnected(pid: string, r: Schemas["RepoOption"] | null) {
  const params = { params: { path: { workspace_id: live.ws!.id, project_id: pid } } };
  if (!r) {
    await unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", params));
    return null;
  }
  return unwrap(api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", { ...params, body: { installation_ref: r.installation_ref, github_repo_id: r.github_repo_id } }));
}
