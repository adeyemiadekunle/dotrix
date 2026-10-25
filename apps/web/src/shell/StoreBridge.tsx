// Mirrors the workspace queries into the synchronous store slots the task kit still reads
// (task(), PopLayer lookups, presence, badges). The queries are the source of truth — these
// arrays are replaced, never merged — while writes keep flowing through live.ts's senders and
// come back here through cache invalidation. The demo (/w/dotrix) is never live, so nothing
// is mirrored and its seeded store is untouched. Deleting a slot's readers lets its mirror go.
import { useEffect } from "react";

import { useCodingSessions } from "../../lib/coding";
import { useCrossConversations } from "../../lib/conversations";
import { toCodingSession, toThread } from "../../lib/view-models";
import { useLiveNotifications, useLiveWorkspaceActivity, useLiveWorkspaceTasks } from "../../lib/workspace-data";
import { isLive, live } from "../data/live";
import { D, render, useStudio } from "../data/store";

export function StoreBridge() {
  useStudio(); // re-render when live.ws appears or the store changes
  const wsId = isLive() ? live.ws?.id : undefined;
  const tasks = useLiveWorkspaceTasks(wsId, Boolean(wsId));
  const notifs = useLiveNotifications(wsId, Boolean(wsId));
  const acts = useLiveWorkspaceActivity(wsId, Boolean(wsId));
  const convos = useCrossConversations(wsId, Boolean(wsId));
  const sessions = useCodingSessions(wsId, Boolean(wsId));
  useEffect(() => {
    if (!wsId) return;
    const d = D();
    if (tasks) d.tasks = tasks;
    if (notifs) d.notifs = notifs;
    if (acts) d.activity = acts;
    if (convos.data) d.threads = convos.data.map(toThread);
    if (sessions.data) d.coding = sessions.data.map(toCodingSession);
    if (tasks || notifs || acts || convos.data || sessions.data) render();
  }, [wsId, tasks, notifs, acts, convos.data, sessions.data]);
  return null;
}
