import type { Schemas } from "@pmagent/api-client";
import { useInfiniteQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import type { Scope } from "./issues";

export type ActivityItem = Schemas["ActivityItem"];

const PAGE = 50;

/** A project's activity, newest first, a page at a time (`fetchNextPage` loads older items). */
export function useProjectActivity(scope: Scope | undefined, limit = PAGE) {
  return useInfiniteQuery({
    queryKey: ["activity", scope?.projectId, limit],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/activity", {
          params: {
            path: { workspace_id: scope!.workspaceId, project_id: scope!.projectId },
            query: { limit, ...(pageParam ? { before: pageParam } : {}) },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.length < limit ? undefined : last[last.length - 1]!.at),
    enabled: Boolean(scope),
  });
}

/** Activity across every project in the workspace you can see, a page at a time; with `agents`,
 * only what agents did. */
export function useWorkspaceActivity(workspaceId: string | undefined, limit = PAGE, { agents = false } = {}) {
  return useInfiniteQuery({
    queryKey: ["activity", "workspace", workspaceId, limit, agents],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/activity", {
          params: {
            path: { workspace_id: workspaceId! },
            query: { limit, ...(agents ? { agents } : {}), ...(pageParam ? { before: pageParam } : {}) },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.length < limit ? undefined : last[last.length - 1]!.at),
    enabled: Boolean(workspaceId),
  });
}
