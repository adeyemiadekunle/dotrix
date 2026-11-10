// The workspace's lists for the screens that show them, like data/tasks.ts does for tasks: the API's
// (TanStack Query) in a real workspace, the store's in the seeded one. A screen reads them here and
// doesn't know which it has; `loading` is true until the API's first answer (never in the sample).
import { useCodingSessions as useLiveCodingSessions } from "../../lib/coding";
import { useCrossConversations } from "../../lib/conversations";
import { readSlot } from "../../lib/store-slots";
import {
  useLiveAgents,
  useLiveAudit,
  useLiveMembers,
  useLiveNotifications,
  useLiveProjectActivity,
  useLiveProjectFiles,
  useLiveProjects,
  useLiveWorkspaceActivity,
  useLiveWorkspaceAutomations,
} from "../../lib/workspace-data";
import { isLive, live } from "./live";
import { D, visibleProjects } from "./store";
import type { Activity, Agent, AuditEvent, Automation, CodingSession, FileItem, Member, Notif, Project, Thread } from "./types";

type List<T> = { items: T[]; loading: boolean };
const from = <T>(on: boolean, api: T[] | undefined, store: () => T[]): List<T> =>
  on ? { items: api ?? [], loading: !api } : { items: store(), loading: false };

/** The workspace's people, with pending email invites. */
export function useMembers(): List<Member> {
  const on = isLive();
  return from(on, useLiveMembers(live.ws?.id, on), () => D().members);
}

/** The projects you can open that aren't archived, in the sidebar's order. */
export function useProjects(): List<Project> {
  const on = isLive();
  const api = useLiveProjects(live.ws?.id, on);
  return from(
    on,
    api &&
      (() => {
        const at = new Map(D().projOrder.map((id, i) => [id, i]));
        return api.filter((p) => !p.archived).sort((a, b) => (at.get(a.id) ?? Infinity) - (at.get(b.id) ?? Infinity));
      })(),
    visibleProjects,
  );
}

/** Your notifications. */
export function useNotifs(): List<Notif> {
  const on = isLive();
  return from(on, useLiveNotifications(live.ws?.id, on), () => D().notifs);
}

/** What happened across the workspace, newest first. */
export function useActivity(): List<Activity> {
  const on = isLive();
  return from(on, useLiveWorkspaceActivity(live.ws?.id, on), () => D().activity);
}

/** A project's activity, newest first. */
export function useProjectActivity(projectId: string): List<Activity> {
  const on = isLive();
  const api = useLiveProjectActivity(on && live.ws ? { workspaceId: live.ws.id, projectId } : undefined);
  return from(on, api, () => D().activity.filter((a) => a.project === projectId));
}

/** A project's uploaded files. */
export function useProjectFiles(projectId: string): List<FileItem> {
  const on = isLive();
  const api = useLiveProjectFiles(on && live.ws ? { workspaceId: live.ws.id, projectId } : undefined);
  return from(on, api, () => D().files.filter((f) => f.project === projectId));
}

/** The automations of every project you can see. */
export function useAutomations(): List<Automation> {
  const on = isLive();
  return from(on, useLiveWorkspaceAutomations(live.ws?.id, on), () => D().automations);
}

/** The workspace's audit log (owners and admins; others get none). */
export function useAudit(): List<AuditEvent> {
  const on = isLive();
  return from(on, useLiveAudit(live.ws?.id, on), () => D().audit);
}

/** The workspace's agents. */
export function useAgents(): List<Agent> {
  const on = isLive();
  return from(on, useLiveAgents(live.ws?.id, on), () => D().agents);
}

/** Your conversations, as the store lists them (the same objects as `D().threads`). */
export function useThreads(): List<Thread> {
  const on = isLive();
  const q = useCrossConversations(live.ws?.id, on);
  return from(on, q.data && live.ws ? readSlot("threads", live.ws.id) : undefined, () => D().threads);
}

/** Kai's coding sessions you can see, as the store lists them (the same objects as `D().coding`). */
export function useCodingSessions(): List<CodingSession> {
  const on = isLive();
  const q = useLiveCodingSessions(live.ws?.id, on);
  return from(on, q.data && live.ws ? readSlot("coding", live.ws.id) : undefined, () => D().coding);
}
