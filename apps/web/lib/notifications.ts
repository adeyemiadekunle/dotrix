import type { Schemas } from "@dotrix/api-client";
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
export type NotificationKind = Schemas["NotificationKind"];

/** Your notifications in a workspace, newest first (`kind` narrows them). */
export function useNotifications(workspaceId: string | undefined, kind?: NotificationKind) {
  return useQuery({
    queryKey: ["notifications", workspaceId, "list", kind ?? "all"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/notifications", {
          params: { path: { workspace_id: workspaceId! }, query: { limit: 100, ...(kind ? { kind } : {}) } },
        }),
      ),
    enabled: Boolean(workspaceId),
    refetchInterval: 20_000,
  });
}
