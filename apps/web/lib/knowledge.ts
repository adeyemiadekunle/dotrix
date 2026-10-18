// The project's .dotrix/ knowledge: files with version history, restore and export.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type Manifest = Schemas["Manifest"];
export type KnowledgeFileRead = Schemas["FileRead"];
export type VersionEntry = Schemas["VersionEntry"];
export type VersionDiff = Schemas["VersionDiff"];

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

function useKnowledgeMutation<Vars>(scope: Scope | undefined, fn: (scope: Scope, vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => fn(scope!, vars),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: all(scope) });
    },
  });
}

/** Write a knowledge file (a person editing it directly; agents write via approvals). */
export function useSaveKnowledgeFile(scope: Scope | undefined) {
  return useKnowledgeMutation(scope, (s, { filePath, content }: { filePath: string; content: string }) =>
    unwrap(
      api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}", {
        params: { path: { ...projectPath(s), path: filePath } },
        body: { content },
      }),
    ),
  );
}

export function useDeleteKnowledgeFile(scope: Scope | undefined) {
  return useKnowledgeMutation(scope, (s, filePath: string) =>
    unwrap(
      api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}", {
        params: { path: { ...projectPath(s), path: filePath } },
      }),
    ),
  );
}

/** Version history of one file. */
export function useKnowledgeVersions(scope: Scope | undefined, filePath: string | undefined) {
  return useQuery({
    queryKey: scope ? [...all(scope), "versions", filePath] : ["knowledge", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}/versions", {
          params: { path: { ...projectPath(scope!), path: filePath! } },
        }),
      ),
    enabled: Boolean(scope && filePath),
  });
}

/** One past version's content. */
export function useKnowledgeVersion(scope: Scope | undefined, filePath: string | undefined, version: number | undefined) {
  return useQuery({
    queryKey: scope ? [...all(scope), "version", filePath, version] : ["knowledge", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}/versions/{version}", {
          params: { path: { ...projectPath(scope!), path: filePath!, version: version! } },
        }),
      ),
    enabled: Boolean(scope && filePath && version != null),
  });
}

/** The diff between a past version and the current file. */
export function useKnowledgeDiff(scope: Scope | undefined, filePath: string | undefined, version: number | undefined) {
  return useQuery({
    queryKey: scope ? [...all(scope), "diff", filePath, version] : ["knowledge", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}/versions/{version}/diff", {
          params: { path: { ...projectPath(scope!), path: filePath!, version: version! } },
        }),
      ),
    enabled: Boolean(scope && filePath && version != null),
  });
}

/** Restore a file to one of its past versions. */
export function useRestoreKnowledgeFile(scope: Scope | undefined) {
  return useKnowledgeMutation(scope, (s, { filePath, version }: { filePath: string; version: number }) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/knowledge/files/{path}/restore", {
        params: { path: { ...projectPath(s), path: filePath } },
        body: { version },
      }),
    ),
  );
}

/** The URL a browser downloads the whole .dotrix/ export from. */
export function knowledgeExportUrl(scope: Scope) {
  return `/v1/workspaces/${scope.workspaceId}/projects/${scope.projectId}/knowledge/export`;
}
