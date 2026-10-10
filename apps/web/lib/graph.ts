// The project graph: how requirements, issues, decisions, documents, and modules connect.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "@/lib/api";
import type { Scope } from "@/lib/issues";

export type GraphNode = Schemas["NodeRead"];
export type GraphLink = Schemas["LinkRead"];
export type EdgeKind = Schemas["EdgeKind"];
export type LinkCreate = Schemas["LinkCreate"];

const path = (scope: Scope) => ({ workspace_id: scope.workspaceId, project_id: scope.projectId });
const keys = {
  all: (scope: Scope) => ["graph", scope.projectId] as const,
  neighbors: (scope: Scope, ref: string) => ["graph", scope.projectId, "neighbors", ref] as const,
  stale: (scope: Scope) => ["graph", scope.projectId, "stale"] as const,
};

/** How a link reads from the side you're looking at. */
export const LINK_LABELS: Record<EdgeKind, { out: string; in: string }> = {
  implements: { out: "Implements", in: "Implemented by" },
  depends_on: { out: "Depends on", in: "Needed by" },
  part_of: { out: "Part of", in: "Contains" },
  decided_by: { out: "Follows the decision", in: "Followed by" },
  affects: { out: "Affects", in: "Affected by" },
  supersedes: { out: "Supersedes", in: "Superseded by" },
  mentions: { out: "Mentions", in: "Mentioned in" },
  relates_to: { out: "Related to", in: "Related to" },
};

/** The kinds people can add by hand (the board's parents and dependencies are set on issues). */
export const LINKABLE: EdgeKind[] = ["relates_to", "implements", "decided_by", "affects", "supersedes", "mentions"];

export function useNeighbors(scope: Scope | undefined, ref: string | null) {
  return useQuery({
    queryKey: scope && ref ? keys.neighbors(scope, ref) : ["graph", "none"],
    enabled: !!scope && !!ref,
    retry: false,
    // Links follow the text: the panel remounts after an edit (keyed by version), and asks again.
    refetchOnMount: "always",
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/neighbors", {
          params: { path: path(scope!), query: { ref: ref! } },
        }),
      ),
  });
}

export function useStale(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? keys.stale(scope) : ["graph", "none"],
    enabled: !!scope,
    refetchOnMount: "always",
    queryFn: () =>
      unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/stale", { params: { path: path(scope!) } })),
  });
}

export function useAddLink(scope: Scope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LinkCreate) =>
      unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/links", { params: { path: path(scope) }, body })),
    onSuccess: () => {
      toast.success("Linked");
      void queryClient.invalidateQueries({ queryKey: keys.all(scope) });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}

export function useRemoveLink(scope: Scope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/links/{link_id}", {
          params: { path: { ...path(scope), link_id: id } },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keys.all(scope) }),
    onError: (error) => toast.error(errorMessage(error)),
  });
}
