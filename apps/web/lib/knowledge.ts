import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import type { Scope } from "./issues";

const projectPath = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });
const all = (s: Scope) => ["knowledge", s.projectId] as const;

/** The .dotrix/ manifest: every knowledge file with its status (the Knowledge tab). */
export function useKnowledge(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? all(scope) : ["knowledge", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge", {
          params: { path: projectPath(scope!) },
        }),
      ),
    enabled: Boolean(scope),
  });
}

/** One knowledge file's current content. */
export function useKnowledgeFile(scope: Scope | undefined, filePath: string | undefined) {
  return useQuery({
    queryKey: scope ? [...all(scope), "file", filePath] : ["knowledge", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}", {
          params: { path: { ...projectPath(scope!), path: filePath! } },
        }),
      ),
    enabled: Boolean(scope && filePath),
  });
}
