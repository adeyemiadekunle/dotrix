import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";

/** The projects you starred in this workspace, in the order you starred them. */
export function useStarredProjects(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["projects", workspaceId, "starred"],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/starred", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: Boolean(workspaceId),
  });
}
