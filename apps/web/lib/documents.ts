import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import type { Scope } from "./issues";

const projectPath = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });
const listKey = (s: Scope) => ["documents", s.projectId] as const;

/** A project's uploaded documents, newest first (Knowledge → Files). */
export function useDocuments(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? listKey(scope) : ["documents", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/documents", {
          params: { path: projectPath(scope!) },
        }),
      ),
    enabled: Boolean(scope),
  });
}
