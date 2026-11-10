import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import type { Scope } from "./issues";

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
