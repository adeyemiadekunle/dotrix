"use client";

// Organisations: they own workspaces and manage people across them, without seeing inside
// (org owners are the exception: they see every workspace the organisation owns).
import type { Schemas } from "@pmagent/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type Org = Schemas["OrgWithRole"];
export type OrgRole = Schemas["OrgRole"];
export type OrgMember = Schemas["OrgMemberRead"];
export type OrgWorkspace = Schemas["OrgWorkspaceRead"];
export type PlaceableRole = Schemas["WorkspacePlacement"]["role"];

export const ORG_ROLE_LABELS: Record<OrgRole, string> = { owner: "Owner", admin: "Admin", member: "Member" };
export const ORG_ROLE_HINTS: Record<OrgRole, string> = {
  owner: "Everything, and sees inside every workspace",
  admin: "Manages people and workspaces; sees inside only the ones they're in",
  member: "Belongs to the organisation; sees their own workspaces",
};

export const canManageOrg = (role: OrgRole | undefined) => role === "owner" || role === "admin";

const org = (orgId: string) => ({ params: { path: { org_id: orgId } } });

export function useOrgs() {
  return useQuery({ queryKey: ["orgs"], queryFn: () => unwrap(api.GET("/v1/organizations")) });
}

/** The organisation in the URL (/o/[org]), by slug. */
export function useCurrentOrg() {
  const params = useParams<{ org?: string }>();
  const orgs = useOrgs();
  const current = orgs.data?.find((o) => o.slug === params.org);
  return { org: current, isLoading: orgs.isLoading, notFound: orgs.isSuccess && !current };
}

export function useOrgMembers(orgId: string | undefined) {
  return useQuery({
    queryKey: ["org-members", orgId],
    queryFn: () => unwrap(api.GET("/v1/organizations/{org_id}/members", org(orgId!))),
    enabled: Boolean(orgId),
  });
}

export function useOrgWorkspaces(orgId: string | undefined) {
  return useQuery({
    queryKey: ["org-workspaces", orgId],
    queryFn: () => unwrap(api.GET("/v1/organizations/{org_id}/workspaces", org(orgId!))),
    enabled: Boolean(orgId),
  });
}

export function useOrgWorkspaceMembers(orgId: string, workspaceId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["org-workspace-members", orgId, workspaceId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/organizations/{org_id}/workspaces/{workspace_id}/members", {
          params: { path: { org_id: orgId, workspace_id: workspaceId } },
        }),
      ),
    enabled,
  });
}

function useOrgMutation<Vars, Result>(fn: (vars: Vars) => Promise<Result>, orgId: string | undefined, success?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      if (success) toast.success(success);
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () =>
      Promise.all(
        [["orgs"], ["org-members", orgId], ["org-workspaces", orgId], ["org-workspace-members", orgId], ["workspaces"]].map(
          (queryKey) => queryClient.invalidateQueries({ queryKey }),
        ),
      ),
  });
}

export function useCreateOrg() {
  return useOrgMutation((name: string) => unwrap(api.POST("/v1/organizations", { body: { name } })), undefined);
}

export function useRenameOrg(orgId: string) {
  return useOrgMutation(
    (name: string) => unwrap(api.PATCH("/v1/organizations/{org_id}", { ...org(orgId), body: { name } })),
    orgId,
    "Organisation renamed",
  );
}

export function useAddOrgMember(orgId: string) {
  return useOrgMutation(
    (body: Schemas["OrgMemberAdd"]) => unwrap(api.POST("/v1/organizations/{org_id}/members", { ...org(orgId), body })),
    orgId,
    "Added to the organisation",
  );
}

export function useChangeOrgRole(orgId: string) {
  return useOrgMutation(
    ({ userId, role }: { userId: string; role: OrgRole }) =>
      unwrap(
        api.PATCH("/v1/organizations/{org_id}/members/{user_id}", {
          params: { path: { org_id: orgId, user_id: userId } },
          body: { role },
        }),
      ),
    orgId,
    "Role changed",
  );
}

export function useRemoveOrgMember(orgId: string) {
  return useOrgMutation(
    (userId: string) =>
      unwrap(
        api.DELETE("/v1/organizations/{org_id}/members/{user_id}", {
          params: { path: { org_id: orgId, user_id: userId } },
        }),
      ),
    orgId,
  );
}

export function useCreateOrgWorkspace(orgId: string) {
  return useOrgMutation(
    (body: Schemas["OrgWorkspaceCreate"]) =>
      unwrap(api.POST("/v1/organizations/{org_id}/workspaces", { ...org(orgId), body })),
    orgId,
    "Workspace created",
  );
}

export function useAttachWorkspace(orgId: string) {
  return useOrgMutation(
    (workspaceId: string) =>
      unwrap(
        api.POST("/v1/organizations/{org_id}/workspaces/attach", { ...org(orgId), body: { workspace_id: workspaceId } }),
      ),
    orgId,
    "Workspace added to the organisation",
  );
}

export function useDetachWorkspace(orgId: string) {
  return useOrgMutation(
    (workspaceId: string) =>
      unwrap(
        api.POST("/v1/organizations/{org_id}/workspaces/{workspace_id}/detach", {
          params: { path: { org_id: orgId, workspace_id: workspaceId } },
        }),
      ),
    orgId,
    "Workspace taken out of the organisation",
  );
}

export function usePlace(orgId: string) {
  return useOrgMutation(
    ({ workspaceId, userId, role }: { workspaceId: string; userId: string; role: PlaceableRole }) =>
      unwrap(
        api.PUT("/v1/organizations/{org_id}/workspaces/{workspace_id}/members/{user_id}", {
          params: { path: { org_id: orgId, workspace_id: workspaceId, user_id: userId } },
          body: { role },
        }),
      ),
    orgId,
  );
}

export function useUnplace(orgId: string) {
  return useOrgMutation(
    ({ workspaceId, userId }: { workspaceId: string; userId: string }) =>
      unwrap(
        api.DELETE("/v1/organizations/{org_id}/workspaces/{workspace_id}/members/{user_id}", {
          params: { path: { org_id: orgId, workspace_id: workspaceId, user_id: userId } },
        }),
      ),
    orgId,
  );
}
