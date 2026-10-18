// Project documents (the Files tab): uploads land in storage and are converted to Markdown
// in the background. Upload uses raw apiFetch with FormData rather than api.POST, which only
// speaks JSON.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, apiFetch, errorMessage, problemMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type Document = Schemas["DocumentRead"];

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

function useDocumentMutation<Vars>(scope: Scope | undefined, fn: (scope: Scope, vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => fn(scope!, vars),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: listKey(scope) });
    },
  });
}

/** Upload a file; conversion to Markdown happens in the background. Progress 0–100. */
export function useUploadDocument(scope: Scope | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, onProgress }: { file: File; onProgress?: (pct: number) => void }) => {
      const body = new FormData();
      body.append("file", file);
      onProgress?.(15);
      const res = await apiFetch(`/v1/workspaces/${scope!.workspaceId}/projects/${scope!.projectId}/documents`, {
        method: "POST",
        body,
      });
      if (!res.ok) {
        const problem = (await res.json().catch(() => undefined)) as Parameters<typeof problemMessage>[0];
        throw new Error(problemMessage(problem) ?? "The file didn't upload");
      }
      onProgress?.(100);
      return (await res.json()) as Document;
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: listKey(scope) });
    },
  });
}

export function useRenameDocument(scope: Scope | undefined) {
  return useDocumentMutation(scope, (s, { documentId, filename }: { documentId: string; filename: string }) =>
    unwrap(
      api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", {
        params: { path: { ...projectPath(s), document_id: documentId } },
        body: { filename },
      }),
    ),
  );
}

export function useDuplicateDocument(scope: Scope | undefined) {
  return useDocumentMutation(scope, (s, documentId: string) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}/duplicate", {
        params: { path: { ...projectPath(s), document_id: documentId } },
      }),
    ),
  );
}

/** Upload the same file again after conversion failed. */
export function useRetryDocument(scope: Scope | undefined) {
  return useDocumentMutation(scope, (s, documentId: string) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}/retry", {
        params: { path: { ...projectPath(s), document_id: documentId } },
      }),
    ),
  );
}

export function useDeleteDocument(scope: Scope | undefined) {
  return useDocumentMutation(scope, (s, documentId: string) =>
    unwrap(
      api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}", {
        params: { path: { ...projectPath(s), document_id: documentId } },
      }),
    ),
  );
}
