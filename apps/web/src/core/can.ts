// What the signed-in person may do here, so a control they can't use isn't shown. In a real
// workspace it's what the API reports for them (their role's permissions plus what the workspace
// grants members); on the seeded demo, owners and admins do everything and members only their
// own work. The API still enforces every one of these.
import type { ApprovalMode } from "@/lib/agent";
import { isLive, live } from "../data/live";
import { me } from "../data/store";

export type Perm =
  | "members:manage" // invite, remove, change roles
  | "projects:manage" // create projects, set them up
  | "workspace:manage" // rename, agents, models, automations, GitHub, audit log
  | "agents:approve"
  | "agents:code"
  | "knowledge:write"
  | "usage:view"
  | "workspace:billing"; // owners only: plan, payment, deleting the workspace

export function allowed(p: Perm): boolean {
  if (isLive()) return !!live.ws?.permissions?.includes(p as never);
  const role = me()?.role;
  return role === "Owner" || role === "Admin";
}

/** The approval modes you may work in here: up to the workspace's cap, and only Manual unless you
 * may approve agent changes. On the seeded demo, all three. */
export function approvalModes(): ApprovalMode[] {
  const all: ApprovalMode[] = ["manual", "accept_edits", "auto"];
  if (!isLive()) return all;
  if (!allowed("agents:approve")) return ["manual"];
  const cap = live.ws?.approval_mode_cap ?? "manual";
  return all.slice(0, all.indexOf(cap) + 1);
}

/** What a new conversation or coding session starts on: the workspace's default, within your modes. */
export function defaultApproval(): ApprovalMode {
  const mine = approvalModes();
  const wanted = isLive() ? (live.ws?.default_approval_mode ?? "manual") : "manual";
  return mine.includes(wanted) ? wanted : "manual";
}

/** Invites: people who manage members. (In a personal workspace that's its owner, whose invite
 * dialog explains it turns into an organisation first.) */
export const canInvite = () => allowed("members:manage");
