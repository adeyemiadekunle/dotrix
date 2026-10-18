// Workspace membership administration (Settings → Members): roles, removal and invites.
// Reading the member list is useMembers in issues.ts.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type Invite = Schemas["InviteRead"];
export type Member = Schemas["MemberRead"];

const membersKey = (workspaceId: string | undefined) => ["members", workspaceId] as const;
const invitesKey = (workspaceId: string | undefined) => ["invites", workspaceId] as const;

export function useInvites(workspaceId: string | undefined) {
  return useQuery({
    queryKey: invitesKey(workspaceId),
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/invites", {
          params: { path: { workspace_id: workspaceId! } },
        }),
      ),
    enabled: Boolean(workspaceId),
  });
}

function useMemberMutation<Vars>(workspaceId: string | undefined, fn: (vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: membersKey(workspaceId) });
      void queryClient.invalidateQueries({ queryKey: invitesKey(workspaceId) });
    },
  });
}

export function useUpdateMemberRole(workspaceId: string | undefined) {
  return useMemberMutation(workspaceId, ({ userId, role }: { userId: string; role: Schemas["MemberRoleUpdate"]["role"] }) =>
    unwrap(
      api.PATCH("/v1/workspaces/{workspace_id}/members/{user_id}", {
        params: { path: { workspace_id: workspaceId!, user_id: userId } },
        body: { role },
      }),
    ),
  );
}

export function useRemoveMember(workspaceId: string | undefined) {
  return useMemberMutation(workspaceId, (userId: string) =>
    unwrap(
      api.DELETE("/v1/workspaces/{workspace_id}/members/{user_id}", {
        params: { path: { workspace_id: workspaceId!, user_id: userId } },
      }),
    ),
  );
}

/** Send email invites; returns the invites the API created. */
export function useSendEmailInvites(workspaceId: string | undefined) {
  return useMemberMutation(workspaceId, (body: Schemas["EmailInviteCreate"]) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/invites", {
        params: { path: { workspace_id: workspaceId! } },
        body,
      }),
    ),
  );
}

/** Create a shareable invite link; the response carries the URL. */
export function useCreateInviteLink(workspaceId: string | undefined) {
  return useMemberMutation(workspaceId, (body: Schemas["LinkInviteCreate"]) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/invites/links", {
        params: { path: { workspace_id: workspaceId! } },
        body,
      }),
    ),
  );
}

export function useRevokeInvite(workspaceId: string | undefined) {
  return useMemberMutation(workspaceId, (inviteId: string) =>
    unwrap(
      api.DELETE("/v1/workspaces/{workspace_id}/invites/{invite_id}", {
        params: { path: { workspace_id: workspaceId!, invite_id: inviteId } },
      }),
    ),
  );
}
