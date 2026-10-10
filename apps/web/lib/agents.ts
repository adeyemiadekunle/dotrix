// Who the agents are: the six built-ins and a workspace's own agents, as contracts owners and
// admins change (Settings → Agents), with per-project overrides. The chat's + menu and the
// names shown on replies come from here.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { toast } from "sonner";

import { AGENTS, type AgentOption } from "./agent";
import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type AgentDef = Schemas["AgentRead"];
export type AgentFields = Schemas["AgentFields"];
export type AgentVersion = Schemas["AgentVersionRead"];
export type AgentCatalog = Schemas["AgentCatalog"];
export type Access = Schemas["Access"];

export const PM_HANDLE = "project-manager";

/** Where agents are defined: the workspace, or one project's overrides. */
export type AgentScope = { workspaceId: string; projectId?: string };

export const agentsKey = (s: AgentScope) => ["agents", s.workspaceId, s.projectId ?? null] as const;

/** "Product agent" (sentence case) from the built-ins' "Product Agent". */
export const displayName = (a: Pick<AgentDef, "name">) => a.name.replace(/ Agent$/, " agent");

export const SOURCE_LABELS: Record<AgentDef["source"], string> = {
  built_in: "Built-in",
  customised: "Customised",
  custom: "Custom",
};

export const ACCESS_LABELS: Record<Access, string> = {
  read: "Read",
  propose: "Propose",
  tidy: "Tidy",
  write: "Write",
};

export const ACTION_LABELS: Record<string, string> = {
  "knowledge.write": "Write documents",
  "issues.create": "Open issues",
  "issues.update": "Edit issues",
  "issues.comment": "Comment on issues",
};

function path(s: AgentScope) {
  return s.projectId ? { workspace_id: s.workspaceId, project_id: s.projectId } : { workspace_id: s.workspaceId };
}

export function useAgents(scope: AgentScope | undefined) {
  return useQuery({
    queryKey: scope ? agentsKey(scope) : ["agents", "none"],
    queryFn: () =>
      scope!.projectId
        ? unwrap(
            api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/agents", {
              params: { path: { workspace_id: scope!.workspaceId, project_id: scope!.projectId } },
            }),
          )
        : unwrap(api.GET("/v1/workspaces/{workspace_id}/agents", { params: { path: { workspace_id: scope!.workspaceId } } })),
    enabled: Boolean(scope),
    staleTime: 60_000,
  });
}

export function useAgentCatalog(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["agent-catalog", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/agents/catalog", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: Boolean(workspaceId),
    staleTime: 10 * 60_000,
  });
}

export function useAgentVersions(scope: AgentScope | undefined, handle: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["agent-versions", scope?.workspaceId, scope?.projectId ?? null, handle],
    queryFn: () =>
      scope!.projectId
        ? unwrap(
            api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/agents/{handle}/versions", {
              params: { path: { workspace_id: scope!.workspaceId, project_id: scope!.projectId, handle: handle! } },
            }),
          )
        : unwrap(
            api.GET("/v1/workspaces/{workspace_id}/agents/{handle}/versions", {
              params: { path: { workspace_id: scope!.workspaceId, handle: handle! } },
            }),
          ),
    enabled: Boolean(scope && handle && enabled),
  });
}

function useAgentMutation<Vars, Result>(scope: AgentScope, fn: (vars: Vars) => Promise<Result>, success?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      if (success) toast.success(success);
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () =>
      Promise.all([
        // A workspace change shows in every project that doesn't override it.
        queryClient.invalidateQueries({ queryKey: ["agents", scope.workspaceId] }),
        queryClient.invalidateQueries({ queryKey: ["agent-versions", scope.workspaceId] }),
      ]),
  });
}

export function useSaveAgent(scope: AgentScope) {
  return useAgentMutation(
    scope,
    ({ handle, body }: { handle: string; body: Schemas["AgentSave"] }) =>
      scope.projectId
        ? unwrap(
            api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/agents/{handle}", {
              params: { path: { ...(path(scope) as { workspace_id: string; project_id: string }), handle } },
              body,
            }),
          )
        : unwrap(
            api.PUT("/v1/workspaces/{workspace_id}/agents/{handle}", {
              params: { path: { workspace_id: scope.workspaceId, handle } },
              body,
            }),
          ),
    "Agent saved",
  );
}

export function useDeleteAgent(scope: AgentScope) {
  return useAgentMutation(scope, (handle: string) =>
    scope.projectId
      ? unwrap(
          api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/agents/{handle}", {
            params: { path: { ...(path(scope) as { workspace_id: string; project_id: string }), handle } },
          }),
        )
      : unwrap(
          api.DELETE("/v1/workspaces/{workspace_id}/agents/{handle}", {
            params: { path: { workspace_id: scope.workspaceId, handle } },
          }),
        ),
  );
}

export function useRestoreAgentVersion(scope: AgentScope) {
  return useAgentMutation(
    scope,
    ({ handle, version }: { handle: string; version: number }) =>
      scope.projectId
        ? unwrap(
            api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agents/{handle}/versions/{version}/restore", {
              params: { path: { ...(path(scope) as { workspace_id: string; project_id: string }), handle, version } },
            }),
          )
        : unwrap(
            api.POST("/v1/workspaces/{workspace_id}/agents/{handle}/versions/{version}/restore", {
              params: { path: { workspace_id: scope.workspaceId, handle, version } },
            }),
          ),
    "Version restored",
  );
}

/** Who can answer in a project's chat: Auto, then every agent it has but the project manager
 * (Auto is the project manager). The built-in list stands in while it loads. */
export function useChatAgents(scope: Scope | undefined): AgentOption[] {
  const agents = useAgents(scope);
  const data = agents.data;
  // Stable between renders, so callers can tell when the list actually changed.
  return useMemo(
    () =>
      data
        ? [AGENTS[0], ...data.filter((a) => a.handle !== PM_HANDLE).map((a) => ({ id: a.handle, name: displayName(a), description: a.description || a.name }))]
        : AGENTS,
    [data],
  );
}
