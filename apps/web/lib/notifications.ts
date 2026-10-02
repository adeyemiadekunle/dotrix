"use client";

import type { Schemas } from "@pmagent/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type Notification = Schemas["NotificationRead"];
export type NotificationKind = Schemas["NotificationKind"];
export type NotificationCounts = Schemas["NotificationCounts"];

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

/** Unread notifications that still need you: the sidebar's badge and the bell's dot. */
export function useNotificationCounts(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["notifications", workspaceId, "counts"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/notifications/counts", { params: { path: { workspace_id: workspaceId! } } }),
      ),
    enabled: Boolean(workspaceId),
    refetchInterval: 20_000,
  });
}

/** Mark some notifications read (`ids`), or all of them (of one `kind`). */
export function useMarkRead(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["MarkRead"]) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/notifications/read", {
          params: { path: { workspace_id: workspaceId! } },
          body,
        }),
      ),
    onSuccess: (counts) => {
      queryClient.setQueryData(["notifications", workspaceId, "counts"], counts);
      void queryClient.invalidateQueries({ queryKey: ["notifications", workspaceId, "list"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}
