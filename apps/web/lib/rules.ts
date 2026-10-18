// Workspace rules (layered under each project's agent-rules/) and the skills every project
// shares (Settings → Agents → Rules and skills tab).
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type WorkspaceRule = Schemas["WorkspaceRuleRead"];
export type WorkspaceSkill = Schemas["WorkspaceSkillRead"];

const wsPath = (workspaceId: string) => ({ params: { path: { workspace_id: workspaceId } } });

export function useWorkspaceRules(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["rules", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/rules", wsPath(workspaceId!))),
    enabled: Boolean(workspaceId),
  });
}

/** Save a rule; `base` is the version it was read at, for optimistic concurrency. */
export function useSaveWorkspaceRule(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ handle, body }: { handle: string; body: Schemas["WorkspaceRuleSave"] }) =>
      unwrap(
        api.PUT("/v1/workspaces/{workspace_id}/rules/{handle}", {
          params: { path: { workspace_id: workspaceId!, handle } },
          body,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["rules", workspaceId] }),
  });
}

export function useWorkspaceSkills(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["skills", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/skills", wsPath(workspaceId!))),
    enabled: Boolean(workspaceId),
  });
}

export function useSaveWorkspaceSkill(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, body }: { name: string; body: Schemas["WorkspaceRuleSave"] }) =>
      unwrap(
        api.PUT("/v1/workspaces/{workspace_id}/skills/{name}", {
          params: { path: { workspace_id: workspaceId!, name } },
          body,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["skills", workspaceId] }),
  });
}
