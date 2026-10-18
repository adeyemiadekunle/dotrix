// Workspace-level writes (rename, convert to an organisation, transfer ownership) and the
// search endpoints.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type WorkspaceSearchHit = Schemas["WorkspaceSearchHit"];
export type SearchHit = Schemas["SearchHit"];
export type SearchSource = Schemas["ChunkSource"];

function useWorkspaceMutation<Vars>(workspaceId: string | undefined, fn: (vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      void queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    },
  });
}

export function useUpdateWorkspace(workspaceId: string | undefined) {
  return useWorkspaceMutation(workspaceId, (body: Schemas["WorkspaceUpdate"]) =>
    unwrap(
      api.PATCH("/v1/workspaces/{workspace_id}", {
        params: { path: { workspace_id: workspaceId! } },
        body,
      }),
    ),
  );
}

/** Turn a personal workspace into an organisation. */
export function useConvertToOrganization(workspaceId: string | undefined) {
  return useWorkspaceMutation(workspaceId, (body: Schemas["OrganizationConversion"]) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/convert-to-organization", {
        params: { path: { workspace_id: workspaceId! } },
        body,
      }),
    ),
  );
}

export function useTransferOwnership(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["OwnershipTransfer"]) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/transfer-ownership", {
          params: { path: { workspace_id: workspaceId! } },
          body,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["members", workspaceId] });
      void queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    },
  });
}

/** Hybrid search across the workspace's documents and issues. Pass an empty string to skip. */
export function useWorkspaceSearch(workspaceId: string | undefined, q: string, source?: SearchSource, limit = 50) {
  return useQuery({
    queryKey: ["search", "workspace", workspaceId, q, source],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/search", {
          params: { path: { workspace_id: workspaceId! }, query: { q, source, limit } },
        }),
      ),
    enabled: Boolean(workspaceId && q.trim()),
  });
}

/** Search within one project. */
export function useProjectSearch(scope: Scope | undefined, q: string, source?: SearchSource, limit = 50) {
  return useQuery({
    queryKey: ["search", "project", scope?.projectId, q, source],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/search", {
          params: {
            path: { workspace_id: scope!.workspaceId, project_id: scope!.projectId },
            query: { q, source, limit },
          },
        }),
      ),
    enabled: Boolean(scope && q.trim()),
  });
}
