// Activity feeds (workspace-wide and per project) and the audit log. The ["activity"] key
// is invalidated by issue mutations, so these refetch when the board changes.
import type { Schemas } from "@dotrix/api-client";
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import type { Scope } from "./issues";

export type ActivityItem = Schemas["ActivityItem"];
export type AuditEvent = Schemas["AuditEventRead"];

const projectPath = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });

/** Everything that happened in the workspace, newest first (the Activity screen). */
export function useWorkspaceActivity(workspaceId: string | undefined, limit = 200) {
  return useQuery({
    queryKey: ["activity", "workspace", workspaceId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/activity", {
          params: { path: { workspace_id: workspaceId! }, query: { limit } },
        }),
      ),
    enabled: Boolean(workspaceId),
  });
}

/** A project's activity feed (the project Activity tab). */
export function useProjectActivity(scope: Scope | undefined, limit = 200) {
  return useQuery({
    queryKey: ["activity", "project", scope?.projectId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/activity", {
          params: { path: projectPath(scope!), query: { limit } },
        }),
      ),
    enabled: Boolean(scope),
  });
}

export interface AuditFilters {
  projectId?: string;
  action?: string;
  limit?: number;
}

/** The workspace's audit log (Settings → Audit log). */
export function useAudit(workspaceId: string | undefined, filters: AuditFilters = {}) {
  return useQuery({
    queryKey: ["audit", workspaceId, filters],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/audit", {
          params: {
            path: { workspace_id: workspaceId! },
            query: { project_id: filters.projectId, action: filters.action, limit: filters.limit ?? 200 },
          },
        }),
      ),
    enabled: Boolean(workspaceId),
    placeholderData: (prev) => prev,
  });
}
