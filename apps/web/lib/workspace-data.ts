// Hooks that give screens the store's view types (Task, Project, Member) straight from the
// API — the read half of the migration off data/store.ts + data/live.ts. Conversions come
// from lib/view-models; writes still flow through the existing actions until the kit moves
// (live.ts's senders invalidate these caches, see invalidateLiveQueries there).
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { api, unwrap } from "./api";
import { useWorkspaceIssues, type WorkspaceIssueFilters } from "./issues";
import { useProjects } from "./queries";
import { useStarredProjects } from "./stars";
import { ms, toMember, toProject, toTask } from "./view-models";
import type { Member, Project, Task } from "@/src/data/types";

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

/** Minutes-since strings: store dates are epoch ms under the same name. */
export { ms };
