// Keeps the workspace's queries loaded for the store. In a real workspace the store's lists
// (`D().tasks`, `.members`, `.projects`, `.notifs`, …) read those queries' cache directly
// (lib/store-slots.ts, data/live.ts); nothing is copied here. This mounts the queries so they
// fetch and stay fresh, redraws the store-reading screens when one changes, keeps the sidebar's
// project order, and says when the directory (members, agents, projects) is ready. The demo
// (/w/dotrix) is never live, so nothing here runs for it.
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useCodingSessions } from "../../lib/coding";
import { useCrossConversations } from "../../lib/conversations";
import {
  useLiveAgents,
  useLiveAudit,
  useLiveMembers,
  useLiveNotifications,
  useLiveProjects,
  useLiveWorkspaceActivity,
  useLiveWorkspaceAutomations,
  useLiveWorkspaceFiles,
  useLiveWorkspaceKnowledge,
  useLiveWorkspaceTasks,
} from "../../lib/workspace-data";
import { isLive, live } from "../data/live";
import { D, render, useStudio } from "../data/store";

export function StoreBridge() {
  useStudio(); // re-render when live.ws appears or the store changes
  const wsId = isLive() ? live.ws?.id : undefined;
  const members = useLiveMembers(wsId, Boolean(wsId));
  const projects = useLiveProjects(wsId, Boolean(wsId));
  const agents = useLiveAgents(wsId, Boolean(wsId));
  const tasks = useLiveWorkspaceTasks(wsId, Boolean(wsId));
  const notifs = useLiveNotifications(wsId, Boolean(wsId));
  const acts = useLiveWorkspaceActivity(wsId, Boolean(wsId));
  const convos = useCrossConversations(wsId, Boolean(wsId));
  const sessions = useCodingSessions(wsId, Boolean(wsId));
  const files = useLiveWorkspaceFiles(wsId, Boolean(wsId));
  const knowledge = useLiveWorkspaceKnowledge(wsId, Boolean(wsId));
  const autos = useLiveWorkspaceAutomations(wsId, Boolean(wsId));
  const audit = useLiveAudit(wsId, Boolean(wsId));
  // A directory request that fails for good shouldn't pin the shell on its loader —
  // loadWorkspace used to throw here; surface the same error screen.
  const dirFailed = useDirectoryFailed(wsId);
  useEffect(() => {
    if (wsId && dirFailed && live.mode === "live") {
      live.mode = "error";
      live.error = "Some of the workspace didn't load.";
      render();
    }
  }, [wsId, dirFailed]);
  useEffect(() => {
    if (!wsId) return;
    const d = D();
    if (projects) {
      // Sidebar order: starred first on first fill, then kept (drags stay), new projects last.
      const kept = d.projOrder.filter((id) => projects.some((p) => p.id === id));
      const fresh = projects.filter((p) => !kept.includes(p.id));
      d.projOrder = kept.length
        ? [...kept, ...fresh.filter((p) => p.fav).map((p) => p.id), ...fresh.filter((p) => !p.fav).map((p) => p.id)]
        : [...projects.filter((p) => p.fav), ...projects.filter((p) => !p.fav)].map((p) => p.id);
    }
    // Once the directory has resolved the shell may mount (screens read me()/proj() synchronously). loadWorkspace
    // clears the flag when it loads the same workspace again, whose queries may answer with nothing new: it's a dep.
    if (members && agents && projects) live.dirReady = true;
    if (members || agents || projects || tasks || notifs || acts || convos.data || sessions.data || files || knowledge || autos || audit) render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, live.dirReady, members, agents, projects, tasks, notifs, acts, convos.data, sessions.data, files, knowledge, autos, audit]);
  return null;
}

/** Whether the workspace's members, projects or agents failed to load: read from the query cache,
 * so nothing here fetches (an observer without a fetch function logs an error whenever it's
 * refetched, and in the sample workspace there is no workspace to fetch for). */
function useDirectoryFailed(wsId: string | undefined): boolean {
  const client = useQueryClient();
  const subscribe = useCallback((onChange: () => void) => client.getQueryCache().subscribe(onChange), [client]);
  return useSyncExternalStore(
    subscribe,
    () => Boolean(wsId) && directoryFailed(["members", "projects", "agents"].map((kind) => client.getQueryState([kind, wsId]))),
  );
}

/** A directory query counts as failed only if it never loaded: a failed background refetch keeps its data on screen. */
export function directoryFailed(states: ({ status: string; data: unknown } | undefined)[]): boolean {
  return states.some((state) => state?.status === "error" && state.data === undefined);
}
