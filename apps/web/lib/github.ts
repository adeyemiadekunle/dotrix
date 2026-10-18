// The GitHub App installations on this workspace and the repos they can reach
// (Settings → GitHub, and connecting a repo to a project — the connect itself is in
// projects.ts).
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type GitHubStatus = Schemas["GitHubStatus"];
export type RepoOption = Schemas["RepoOption"];

const wsPath = (workspaceId: string) => ({ params: { path: { workspace_id: workspaceId } } });

export function useGitHubStatus(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["github", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/github", wsPath(workspaceId!))),
    enabled: Boolean(workspaceId),
  });
}

/** Repos the workspace's installations can connect to projects. */
export function useGitHubRepos(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["github", workspaceId, "repos"],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/github/repos", wsPath(workspaceId!))),
    enabled: Boolean(workspaceId),
  });
}

export function useRemoveGitHubInstallation(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (installationRef: string) =>
      unwrap(
        api.DELETE("/v1/workspaces/{workspace_id}/github/installations/{installation_ref}", {
          params: { path: { workspace_id: workspaceId!, installation_ref: installationRef } },
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["github", workspaceId] }),
  });
}
