import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import type { Scope } from "./issues";

const projectPath = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });
const all = (s: Scope) => ["graph", s.projectId] as const;

export function useGraphNeighbors(scope: Scope | undefined, ref: string | undefined) {
  return useQuery({
    queryKey: scope ? [...all(scope), "neighbors", ref] : ["graph", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/neighbors", {
          params: { path: projectPath(scope!), query: { ref: ref! } },
        }),
      ),
    enabled: Boolean(scope && ref),
  });
}
