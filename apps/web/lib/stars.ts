import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "@/lib/api";

/** The projects you starred in this workspace, in the order you starred them. */
export function useStarredProjects(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["projects", workspaceId, "starred"],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/starred", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: Boolean(workspaceId),
  });
}

/** Star or unstar a project for yourself (shown at once, put back if the request fails). */
export function useToggleStar(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  const key = ["projects", workspaceId, "starred"];
  return useMutation({
    mutationFn: async ({ projectId, starred }: { projectId: string; starred: boolean }) => {
      const params = { params: { path: { workspace_id: workspaceId!, project_id: projectId } } };
      await unwrap(
        starred
          ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params)
          : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/star", params),
      );
    },
    onMutate: async ({ projectId, starred }) => {
      await queryClient.cancelQueries({ queryKey: key });
      const before = queryClient.getQueryData<string[]>(key);
      queryClient.setQueryData<string[]>(key, (ids = []) =>
        starred ? [...ids.filter((id) => id !== projectId), projectId] : ids.filter((id) => id !== projectId),
      );
      return { before };
    },
    onError: (e, _vars, context) => {
      queryClient.setQueryData(key, context?.before);
      toast.error(errorMessage(e));
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: key }),
  });
}

/** Starred projects first (in the order starred), then the rest in their own order. */
export function starredFirst<T extends { id: string }>(projects: T[], starred: string[] | undefined): T[] {
  if (!starred?.length) return projects;
  const rank = new Map(starred.map((id, i) => [id, i]));
  return [...projects].sort((a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity));
}
