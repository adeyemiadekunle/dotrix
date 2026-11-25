// What this server offers (`GET /v1/features`), so the app shows only what works here.
// Team workspaces: personal workspaces launch first, and a server with teams turned off
// lists only personal workspaces and refuses the rest, so the app hides every way to make,
// join or reach one. The seeded sample keeps them, as it always has.
import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api";
import { queryClient } from "@/lib/queryClient";

import { isLive } from "../data/live";
import { D } from "../data/store";

type Features = Schemas["Features"];

export const featuresQuery = {
  queryKey: ["features"],
  queryFn: (): Promise<Features> => unwrap(api.GET("/v1/features")),
  staleTime: Infinity,
};

/** For screens outside the workspace (onboarding): false until the server says otherwise. */
export function useTeams(): boolean {
  return useQuery(featuresQuery).data?.teams ?? false;
}

/** Inside a workspace: the live workspace's loader fetched the features first. */
export function teams(): boolean {
  if (!isLive()) return true;
  return queryClient.getQueryData<Features>(featuresQuery.queryKey)?.teams ?? false;
}

/** A personal workspace is just its owner's: no members, teams, roles, or invites to show. */
export const personal = () => D().ws.kind === "personal";

/** Your tasks: in a personal workspace every task is yours (unassigned ones, and those you gave
 * an agent, included); elsewhere the ones assigned to you. */
export const isMine = (t: { assignee?: string | null }) => personal() || t.assignee === D().me;

/** What the tasks page is called: Tasks when they're all yours, My Tasks in a Team workspace. */
export const tasksLabel = () => (personal() ? "Tasks" : "My Tasks");
