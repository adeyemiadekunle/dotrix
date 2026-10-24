// A connected repository's inventory and what its knowledge covers: every tracked path at a commit,
// classified without running anything, and each required domain's coverage or named gap.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type Coverage = Schemas["RepoCoverageRead"];
export type DomainCoverage = Schemas["DomainCoverage"];
export type RepoPath = Schemas["RepoPathRead"];
export type PathStatus = Schemas["PathStatus"];
export type RepoPage = Schemas["RepoPageRead"];

const path = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });
const key = (s: Scope | undefined) => ["repo-knowledge", s?.projectId] as const;

export function useRepoCoverage(scope: Scope | undefined) {
  return useQuery({
    queryKey: [...key(scope), "coverage"],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/knowledge", { params: { path: path(scope!) } })),
    enabled: Boolean(scope),
  });
}

/** The latest inventory's paths, filtered by status or domain (the first 200 in path order). */
export function useRepoPaths(scope: Scope | undefined, filter: { status?: PathStatus; domain?: string }, enabled = true) {
  return useQuery({
    queryKey: [...key(scope), "paths", filter.status ?? null, filter.domain ?? null],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/knowledge/paths", {
          params: { path: path(scope!), query: { status: filter.status, domain: filter.domain, limit: 200 } },
        }),
      ),
    enabled: Boolean(scope) && enabled,
  });
}

export function useTakeInventory(scope: Scope | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/knowledge/inventory", { params: { path: path(scope!) } })),
    onSuccess: (s) => toast.success(`Inventory of ${s.repo_full_name} at ${s.commit_sha.slice(0, 7)}: ${s.path_count} paths`),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: key(scope) }),
  });
}

/** The wiki's pages (docs/wiki/), each with the cited paths that make it stale. */
export function useRepoPages(scope: Scope | undefined) {
  return useQuery({
    queryKey: [...key(scope), "pages"],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/knowledge/pages", { params: { path: path(scope!) } })),
    enabled: Boolean(scope),
  });
}

/** The documentation agent explains the repository in the wiki: a new conversation, opened in Chat. */
export function useExplainRepository(scope: Scope | undefined, opened: (threadId: string) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ domains = [], refresh = false }: { domains?: string[]; refresh?: boolean }) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/knowledge/explain", {
          params: { path: path(scope!) },
          body: { domains, refresh },
        }),
      ),
    onSuccess: (run) => opened(run.thread_id),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: key(scope) }),
  });
}
