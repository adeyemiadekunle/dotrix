// Hooks that give screens the store's view types (Task, Project, Member) straight from the
// API — the read half of the migration off data/store.ts + data/live.ts. Conversions come
// from lib/view-models; writes still flow through the existing actions until the kit moves
// (live.ts's senders invalidate these caches, see invalidateLiveQueries there).
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { api, unwrap } from "./api";
import { useProjectActivity, useWorkspaceActivity } from "./activity";
import { useDocuments } from "./documents";
import { useWorkspaceIssues, type Scope, type WorkspaceIssueFilters } from "./issues";
import { useKnowledge, useKnowledgeFile } from "./knowledge";
import { useNotifications } from "./notifications";
import { useProjects } from "./queries";
import { useStarredProjects } from "./stars";
import { ms, toActivity, toAgent, toFile, toMember, toNotif, toProject, toTask } from "./view-models";
import type { Activity, Agent, FileItem, KnowledgeFile, Member, Notif, Project, Task } from "@/src/data/types";

/** Workspace issues as store Tasks: `fav` comes from the starred set, project ids are real. */
function useLiveTasks(workspaceId: string | undefined, filters: WorkspaceIssueFilters, enabled: boolean): Task[] | undefined {
  const issues = useWorkspaceIssues(enabled ? workspaceId : undefined, filters);
  const starred = useQuery({
    queryKey: ["issues", "workspace", workspaceId, "starred-keys"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/issues", {
          params: { path: { workspace_id: workspaceId! }, query: { starred: true, limit: 5000 } },
        }),
      ),
    enabled: enabled && Boolean(workspaceId),
  });
  return useMemo(() => {
    if (!issues.data) return undefined;
    const fav = new Set((starred.data ?? []).map((i) => i.key));
    return issues.data.map((i, order) => ({ ...toTask(i, i.project_id, order), fav: fav.has(i.key) }));
  }, [issues.data, starred.data]);
}

/** Issues assigned to you across every project you can see (My Tasks → Assigned). */
export function useLiveMyTasks(workspaceId: string | undefined, enabled = true) {
  return useLiveTasks(workspaceId, { assignee: "me" }, enabled);
}

/** Issues you starred (My Tasks → Starred). */
export function useLiveStarredTasks(workspaceId: string | undefined, enabled = true) {
  const tasks = useLiveTasks(workspaceId, { starred: true }, enabled);
  return useMemo(() => tasks?.map((t) => ({ ...t, fav: true })), [tasks]);
}

/** Archived issues across your projects, newest archived first (My Tasks → Archived). */
export function useLiveArchivedTasks(workspaceId: string | undefined, enabled = true) {
  const tasks = useLiveTasks(workspaceId, { archived: "only" }, enabled);
  return useMemo(() => tasks?.slice().sort((a, b) => (b.archivedAt ?? 0) - (a.archivedAt ?? 0)), [tasks]);
}

/** Every non-archived issue across the workspace's visible projects (Home's stats). */
export function useLiveAllTasks(workspaceId: string | undefined, enabled = true) {
  return useLiveTasks(workspaceId, {}, enabled);
}

/** The signed-in person's notifications as store Notifs (Home's waiting card, the Inbox). */
export function useLiveNotifications(workspaceId: string | undefined, enabled = true): Notif[] | undefined {
  const notifs = useNotifications(enabled ? workspaceId : undefined);
  return useMemo(() => notifs.data?.map(toNotif), [notifs.data]);
}

/** The workspace activity feed as store Activity rows (the /activity page). */
export function useLiveWorkspaceActivity(workspaceId: string | undefined, enabled = true): Activity[] | undefined {
  const feed = useWorkspaceActivity(enabled ? workspaceId : undefined);
  return useMemo(() => feed.data?.map(toActivity), [feed.data]);
}

/** A project's activity feed as store Activity rows (the project Activity tab / overview rail). */
export function useLiveProjectActivity(scope: Scope | undefined, enabled = true): Activity[] | undefined {
  const feed = useProjectActivity(enabled ? scope : undefined);
  return useMemo(() => feed.data?.map(toActivity), [feed.data]);
}

/** A project's non-archived issues as store Tasks (Board and List). */
export function useLiveProjectTasks(workspaceId: string | undefined, projectId: string | undefined, enabled = true) {
  const tasks = useLiveTasks(workspaceId, {}, enabled && Boolean(projectId));
  return useMemo(() => tasks?.filter((t) => t.project === projectId && !t.archived), [tasks, projectId]);
}

/** Workspace members as store Members. */
export function useLiveMembers(workspaceId: string | undefined, enabled = true): Member[] | undefined {
  const members = useQuery({
    queryKey: ["members", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/members", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: enabled && Boolean(workspaceId),
    staleTime: 5 * 60_000,
  });
  return useMemo(() => members.data?.map(toMember), [members.data]);
}

/** The workspace's agent contracts as store Agents (Chat's list, Settings → Agents). */
export function useLiveAgents(workspaceId: string | undefined, enabled = true): Agent[] | undefined {
  const agents = useQuery({
    queryKey: ["agents", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/agents", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: enabled && Boolean(workspaceId),
    staleTime: 5 * 60_000,
  });
  return useMemo(() => agents.data?.map(toAgent), [agents.data]);
}

/** The workspace's projects as store Projects (starred and member lists resolved). */
export function useLiveProjects(workspaceId: string | undefined, enabled = true): Project[] | undefined {
  const projects = useProjects(enabled ? workspaceId : undefined);
  const starred = useStarredProjects(enabled ? workspaceId : undefined);
  const members = useQuery({
    queryKey: ["members", workspaceId, "raw"],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/members", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: enabled && Boolean(workspaceId),
    staleTime: 5 * 60_000,
  });
  return useMemo(() => {
    if (!projects.data || !members.data) return undefined;
    const stars = new Set(starred.data ?? []);
    return projects.data.map((p) => toProject(p, members.data, stars));
  }, [projects.data, starred.data, members.data]);
}

/** A project's .dotrix/ manifest as store KnowledgeFiles (paths + versions; content is ""). */
export function useLiveKnowledgeFiles(scope: Scope | undefined, enabled = true): KnowledgeFile[] | undefined {
  const manifest = useKnowledge(enabled ? scope : undefined);
  return useMemo(
    () =>
      !manifest.data || !scope
        ? undefined
        : manifest.data.files
            .filter((f) => !f.deleted)
            .map((f) => ({ path: f.path, project: scope.projectId, content: "", version: f.version, by: "", at: ms(f.updated_at) })),
    [manifest.data, scope],
  );
}

/** One knowledge file with its content (the open file in the Knowledge editor). */
export function useLiveKnowledgeFile(scope: Scope | undefined, path: string | undefined, enabled = true): KnowledgeFile | undefined {
  const file = useKnowledgeFile(enabled ? scope : undefined, path);
  return useMemo(
    () =>
      !file.data || !scope
        ? undefined
        : { path: file.data.path, project: scope.projectId, content: file.data.content, version: file.data.version, by: "", at: ms(file.data.updated_at) },
    [file.data, scope],
  );
}

/** A project's uploaded documents as store FileItems (Knowledge → Files). */
export function useLiveProjectFiles(scope: Scope | undefined, enabled = true): FileItem[] | undefined {
  const docs = useDocuments(enabled ? scope : undefined);
  return useMemo(() => (docs.data && scope ? docs.data.map((d) => toFile(d, scope.projectId)) : undefined), [docs.data, scope]);
}

/** Minutes-since strings: store dates are epoch ms under the same name. */
export { ms };
