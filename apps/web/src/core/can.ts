// What the signed-in person may do here, so a control they can't use isn't shown. In a real
// workspace it's what the API reports for them (their role's permissions plus what the workspace
// grants members); on the seeded demo, owners and admins do everything and members only their
// own work. The API still enforces every one of these.
import type { Approval, ApprovalMode } from "@/lib/agent";
import { isLive, live } from "../data/live";
import { me } from "../data/store";
import { personal } from "./features";

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

/** Team issue creation and assignment are reserved for Owners and Admins. */
export function canManageIssues(): boolean {
  return !isLive() || live.ws?.role === "owner" || live.ws?.role === "admin";
}

/** Changes that require an Owner or Admin even when a Member can approve a run. */
export function canApplyAgentApproval(approval: Pick<Approval, "tool" | "args">): boolean {
  return (
    canManageIssues() ||
    (approval.tool !== "write_file" &&
      approval.tool !== "edit_file" &&
      !(["update_issue", "update_task"].includes(approval.tool) && approval.args?.status === "done"))
  );
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

/** Invites: people who manage members, and only in a Team workspace (a personal workspace is
 * just its owner's; the API refuses its invites too). */
export const canInvite = () => allowed("members:manage") && !personal();
