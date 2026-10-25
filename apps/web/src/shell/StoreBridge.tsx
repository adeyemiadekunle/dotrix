// Mirrors the workspace queries into the synchronous store slots the task kit still reads
// (task(), proj()/who()/mem() lookups, PopLayer, presence, badges). The queries are the source
// of truth — these arrays are replaced, never merged — while writes keep flowing through
// live.ts's senders and come back here through cache invalidation. The demo (/w/dotrix) is
// never live, so nothing is mirrored and its seeded store is untouched. Deleting a slot's
// readers lets its mirror go.
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { useCodingSessions } from "../../lib/coding";
import { useCrossConversations } from "../../lib/conversations";
import { toCodingSession, toThread } from "../../lib/view-models";
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
  // loadWorkspace used to throw here; surface the same error screen. (enabled: false —
  // these only watch the real queries' state, they fetch nothing themselves.)
  const membersFailed = useQuery({ queryKey: ["members", wsId], enabled: false }).isError;
  const projectsFailed = useQuery({ queryKey: ["projects", wsId], enabled: false }).isError;
  const agentsFailed = useQuery({ queryKey: ["agents", wsId], enabled: false }).isError;
  const dirFailed = membersFailed || projectsFailed || agentsFailed;
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
    if (members) d.members = members;
    if (agents) d.agents = agents;
    if (projects) {
      d.projects = projects;
      // Sidebar order: starred first on first fill, then kept (drags stay), new projects last.
      const kept = d.projOrder.filter((id) => projects.some((p) => p.id === id));
      const fresh = projects.filter((p) => !kept.includes(p.id));
      d.projOrder = kept.length
        ? [...kept, ...fresh.filter((p) => p.fav).map((p) => p.id), ...fresh.filter((p) => !p.fav).map((p) => p.id)]
        : [...projects.filter((p) => p.fav), ...projects.filter((p) => !p.fav)].map((p) => p.id);
    }
    if (tasks) d.tasks = tasks;
    if (notifs) d.notifs = notifs;
    if (acts) d.activity = acts;
    if (convos.data) d.threads = convos.data.map(toThread);
    if (sessions.data) d.coding = sessions.data.map(toCodingSession);
    if (files) d.files = files;
    if (knowledge) d.knowledge = knowledge;
    if (autos) d.automations = autos;
    if (audit) d.audit = audit;
    // Once the directory has resolved the shell may mount (screens read me()/proj() synchronously).
    if (members && agents && projects) live.dirReady = true;
    if (members || agents || projects || tasks || notifs || acts || convos.data || sessions.data || files || knowledge || autos || audit) render();
    // mirrorRev is in the deps so a failed send re-runs this and overwrites the optimistic edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsId, live.mirrorRev, members, agents, projects, tasks, notifs, acts, convos.data, sessions.data, files, knowledge, autos, audit]);
  return null;
}
