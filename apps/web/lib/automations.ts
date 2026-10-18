// A project's automations: agents that run on schedules or events.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type Automation = Schemas["AutomationRead"];
export type AutomationCreate = Schemas["AutomationCreate"];
export type AutomationUpdate = Schemas["AutomationUpdate"];

const projectPath = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });
const listKey = (s: Scope) => ["automations", s.projectId] as const;

export function useAutomations(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? listKey(scope) : ["automations", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/automations", {
          params: { path: projectPath(scope!) },
        }),
      ),
    enabled: Boolean(scope),
  });
}

function useAutomationMutation<Vars>(scope: Scope | undefined, fn: (scope: Scope, vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => fn(scope!, vars),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: listKey(scope) });
    },
  });
}

export function useCreateAutomation(scope: Scope | undefined) {
  return useAutomationMutation(scope, (s, body: AutomationCreate) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/automations", {
        params: { path: projectPath(s) },
        body,
      }),
    ),
  );
}

export function useUpdateAutomation(scope: Scope | undefined) {
  return useAutomationMutation(scope, (s, { automationId, changes }: { automationId: string; changes: AutomationUpdate }) =>
    unwrap(
      api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
        params: { path: { ...projectPath(s), automation_id: automationId } },
        body: changes,
      }),
    ),
  );
}

export function useDeleteAutomation(scope: Scope | undefined) {
  return useAutomationMutation(scope, (s, automationId: string) =>
    unwrap(
      api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
        params: { path: { ...projectPath(s), automation_id: automationId } },
      }),
    ),
  );
}

/** Run an automation now, outside its schedule. */
export function useRunAutomation(scope: Scope | undefined) {
  return useAutomationMutation(scope, (s, automationId: string) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}/run", {
        params: { path: { ...projectPath(s), automation_id: automationId } },
      }),
    ),
  );
}
