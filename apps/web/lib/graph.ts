// The project graph: nodes and links derived from issues and documents. Used for
// neighbours, blast radius ("this change affects these docs"), and stale-document detection.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type Subgraph = Schemas["SubgraphRead"];
export type Neighbors = Schemas["NeighborsRead"];
export type ImpactItem = Schemas["ImpactItem"];
export type PathStep = Schemas["PathStep"];
export type StaleDocument = Schemas["StaleRead"];

const projectPath = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });
const all = (s: Scope) => ["graph", s.projectId] as const;

/** The graph around one ref (e.g. an issue key or a document path) to a given depth. */
export function useGraphView(scope: Scope | undefined, ref: string | undefined, depth = 2) {
  return useQuery({
    queryKey: scope ? [...all(scope), "view", ref, depth] : ["graph", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/view", {
          params: { path: projectPath(scope!), query: { ref: ref!, depth } },
        }),
      ),
    enabled: Boolean(scope && ref),
  });
}

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

/** What changing `ref` would reach: the blast radius used for stale-doc warnings. */
export function useGraphImpact(scope: Scope | undefined, ref: string | undefined, depth = 3) {
  return useQuery({
    queryKey: scope ? [...all(scope), "impact", ref, depth] : ["graph", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/impact", {
          params: { path: projectPath(scope!), query: { ref: ref!, depth } },
        }),
      ),
    enabled: Boolean(scope && ref),
  });
}

export function useGraphPath(scope: Scope | undefined, from: string | undefined, to: string | undefined) {
  return useQuery({
    queryKey: scope ? [...all(scope), "path", from, to] : ["graph", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/path", {
          params: { path: projectPath(scope!), query: { from: from!, to: to! } },
        }),
      ),
    enabled: Boolean(scope && from && to),
  });
}

/** Documents that look out of date given recent changes (Home / Knowledge warnings). */
export function useStaleDocuments(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? [...all(scope), "stale"] : ["graph", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/stale", {
          params: { path: projectPath(scope!) },
        }),
      ),
    enabled: Boolean(scope),
  });
}

export function useCreateLink(scope: Scope | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (link: Schemas["LinkCreate"]) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/links", {
          params: { path: projectPath(scope!) },
          body: link,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: all(scope) });
    },
  });
}

export function useDeleteLink(scope: Scope | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) =>
      unwrap(
        api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/links/{link_id}", {
          params: { path: { ...projectPath(scope!), link_id: linkId } },
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: all(scope) });
    },
  });
}
