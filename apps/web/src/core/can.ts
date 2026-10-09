// What the signed-in person may do here, so a control they can't use isn't shown. In a real
// workspace it's what the API reports for them (their role's permissions plus what the workspace
// grants members); on the seeded demo, owners and admins do everything and members only their
// own work. The API still enforces every one of these.
import { isLive, live } from "../data/live";
import { me } from "../data/store";

export type Perm =
  | "members:manage" // invite, remove, change roles, teams
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

/** Invites: people who manage members. (In a personal workspace that's its owner, whose invite
 * dialog explains it turns into an organisation first.) */
export const canInvite = () => allowed("members:manage");
