import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";

export type GitHubStatus = Schemas["GitHubStatus"];
export type RepoOption = Schemas["RepoOption"];
export type ConnectedRepo = Schemas["ConnectedRepoRead"];

/** Whether the GitHub App is set up, and the accounts it's installed on for this workspace (owners and admins). */
export function useGitHubStatus(workspaceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["github", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/github", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: !!workspaceId && enabled,
  });
}

/** Every repo the workspace's installations can see, and which project uses each. */
export function useGitHubRepos(workspaceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["github", workspaceId, "repos"],
    queryFn: () =>
      unwrap(api.GET("/v1/workspaces/{workspace_id}/github/repos", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: !!workspaceId && enabled,
  });
}

/** The repo a project's code lives in, through the GitHub App (null if none). */
export function useProjectRepository(workspaceId: string | undefined, projectId: string | undefined) {
  return useQuery({
    queryKey: ["project-repository", workspaceId, projectId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", {
          params: { path: { workspace_id: workspaceId!, project_id: projectId! } },
        }),
      ),
    enabled: !!workspaceId && !!projectId,
  });
}

/** Connect a project to a repo (or disconnect it with `null`); the project's repo address follows. */
export function useConnectRepository(workspaceId: string, projectId: string) {
  const queryClient = useQueryClient();
  const path = { workspace_id: workspaceId, project_id: projectId };
  return useMutation({
    mutationFn: async (repo: Pick<RepoOption, "installation_ref" | "github_repo_id"> | null) => {
      if (repo === null) {
        await unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", { params: { path } }));
        return null;
      }
      return unwrap(
        api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", {
          params: { path },
          body: { installation_ref: repo.installation_ref, github_repo_id: repo.github_repo_id },
        }),
      );
    },
    onSuccess: (connected) => {
      queryClient.setQueryData(["project-repository", workspaceId, projectId], connected);
      void queryClient.invalidateQueries({ queryKey: ["github", workspaceId, "repos"] });
      void queryClient.invalidateQueries({ queryKey: ["projects", workspaceId] });
    },
  });
}

/** Check the project's code out afresh for agents ("Sync now"); the result comes back on the repo. */
export function useSyncRepository(workspaceId: string, projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/sync", {
          params: { path: { workspace_id: workspaceId, project_id: projectId } },
        }),
      ),
    onSuccess: (repo) => queryClient.setQueryData(["project-repository", workspaceId, projectId], repo),
  });
}

/** Where to install the app: our route remembers the workspace, then GitHub's install page. */
export function installHref(status: GitHubStatus, workspaceId: string, next: string): string | null {
  if (!status.install_url) return null;
  const params = new URLSearchParams({ workspace: workspaceId, install_url: status.install_url, next });
  return `/api/github/install?${params}`;
}
