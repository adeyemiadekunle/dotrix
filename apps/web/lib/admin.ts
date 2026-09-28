"use client";

// Workspace administration: settings, members, invites, the audit log, and project settings.
import type { Schemas } from "@pmagent/api-client";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type Member = Schemas["MemberRead"];
export type Invite = Schemas["InviteRead"];
export type AuditEvent = Schemas["AuditEventRead"];
export type Role = Schemas["Role"];

const ws = (workspaceId: string) => ({ params: { path: { workspace_id: workspaceId } } });

/** Mutations toast their failure and refresh the given queries when they settle. */
function useAdminMutation<Vars, Result>(fn: (vars: Vars) => Promise<Result>, refresh: unknown[][], success?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      if (success) toast.success(success);
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => Promise.all(refresh.map((queryKey) => queryClient.invalidateQueries({ queryKey }))),
  });
}

export function useRenameWorkspace(workspaceId: string) {
  return useAdminMutation(
    (name: string) => unwrap(api.PATCH("/v1/workspaces/{workspace_id}", { ...ws(workspaceId), body: { name } })),
    [["workspaces"]],
    "Workspace renamed",
  );
}

/** What members may do beyond chatting, brainstorming, and working the board. */
export function useMemberPermissions(workspaceId: string) {
  return useAdminMutation(
    (permissions: Schemas["Permission"][]) =>
      unwrap(
        api.PATCH("/v1/workspaces/{workspace_id}", { ...ws(workspaceId), body: { member_permissions: permissions } }),
      ),
    [["workspaces"]],
    "Member permissions saved",
  );
}

export function useChangeRole(workspaceId: string) {
  return useAdminMutation(
    ({ userId, role }: { userId: string; role: Role }) =>
      unwrap(
        api.PATCH("/v1/workspaces/{workspace_id}/members/{user_id}", {
          params: { path: { workspace_id: workspaceId, user_id: userId } },
          body: { role },
        }),
      ),
    [["members", workspaceId], ["workspaces"]],
    "Role changed",
  );
}

export function useRemoveMember(workspaceId: string) {
  return useAdminMutation(
    (userId: string) =>
      unwrap(
        api.DELETE("/v1/workspaces/{workspace_id}/members/{user_id}", {
          params: { path: { workspace_id: workspaceId, user_id: userId } },
        }),
      ),
    [["members", workspaceId], ["workspaces"]],
  );
}

export function useTransferOwnership(workspaceId: string) {
  return useAdminMutation(
    (userId: string) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/transfer-ownership", { ...ws(workspaceId), body: { user_id: userId } }),
      ),
    [["members", workspaceId], ["workspaces"]],
    "Ownership transferred",
  );
}

export function useInvites(workspaceId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["invites", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/invites", ws(workspaceId!))),
    enabled: Boolean(workspaceId) && enabled,
  });
}

export function useInviteByEmail(workspaceId: string) {
  return useAdminMutation(
    (body: Schemas["EmailInviteCreate"]) =>
      unwrap(api.POST("/v1/workspaces/{workspace_id}/invites", { ...ws(workspaceId), body })),
    [["invites", workspaceId]],
    "Invite sent",
  );
}

export function useCreateInviteLink(workspaceId: string) {
  return useAdminMutation(
    (body: Schemas["LinkInviteCreate"]) =>
      unwrap(api.POST("/v1/workspaces/{workspace_id}/invites/links", { ...ws(workspaceId), body })),
    [["invites", workspaceId]],
  );
}

export function useRevokeInvite(workspaceId: string) {
  return useAdminMutation(
    (inviteId: string) =>
      unwrap(
        api.DELETE("/v1/workspaces/{workspace_id}/invites/{invite_id}", {
          params: { path: { workspace_id: workspaceId, invite_id: inviteId } },
        }),
      ),
    [["invites", workspaceId]],
    "Invite revoked",
  );
}

const AUDIT_PAGE = 50;

/** Newest first, paged backwards by the last event's time. */
export function useAuditLog(workspaceId: string | undefined, filters: { projectId?: string; action?: string }) {
  return useInfiniteQuery({
    queryKey: ["audit", workspaceId, filters],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/audit", {
          params: {
            path: { workspace_id: workspaceId! },
            query: {
              project_id: filters.projectId || undefined,
              action: filters.action || undefined,
              before: pageParam ?? undefined,
              limit: AUDIT_PAGE,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => (last.length === AUDIT_PAGE ? last.at(-1)!.created_at : undefined),
    enabled: Boolean(workspaceId),
  });
}

export function useUpdateProject(workspaceId: string, projectId: string) {
  return useAdminMutation(
    (body: Schemas["ProjectUpdate"]) =>
      unwrap(
        api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}", {
          params: { path: { workspace_id: workspaceId, project_id: projectId } },
          body,
        }),
      ),
    [["projects", workspaceId]],
    "Project updated",
  );
}
