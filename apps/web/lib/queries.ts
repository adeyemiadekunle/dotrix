// Shared queries. Keys are arrays starting with the resource, so a mutation can invalidate
// everything under it (e.g. ["projects", workspaceId]).
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";

export function useProjects(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["projects", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: Boolean(workspaceId),
  });
}
