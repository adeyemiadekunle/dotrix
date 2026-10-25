// Agent contracts and model keys the workspace's owners manage (Settings → Agents and
// Models). Runs themselves are in agent.ts.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type Agent = Schemas["AgentRead"];
export type AgentCatalog = Schemas["AgentCatalog"];
export type AgentVersion = Schemas["AgentVersionRead"];
export type ModelKey = Schemas["ModelKeyRead"];

const wsPath = (workspaceId: string) => ({ params: { path: { workspace_id: workspaceId } } });
const agentsKey = (workspaceId: string | undefined) => ["agents-admin", workspaceId] as const;

/** Every agent contract in the workspace (Settings → Agents). */
export function useAgentContracts(workspaceId: string | undefined) {
  return useQuery({
    queryKey: agentsKey(workspaceId),
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/agents", wsPath(workspaceId!))),
    enabled: Boolean(workspaceId),
  });
}

/** The built-in agents a workspace can turn on or base a contract on. */
export function useAgentCatalog(workspaceId: string | undefined) {
  return useQuery({
    queryKey: [...agentsKey(workspaceId), "catalog"],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/agents/catalog", wsPath(workspaceId!))),
    enabled: Boolean(workspaceId),
  });
}

/** One agent's resolved contract plus its version history. */
export function useAgentDetail(workspaceId: string | undefined, handle: string | undefined) {
  return useQuery({
    queryKey: [...agentsKey(workspaceId), handle],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/agents/{handle}", {
          params: { path: { workspace_id: workspaceId!, handle: handle! } },
        }),
      ),
    enabled: Boolean(workspaceId && handle),
  });
}

function useAgentMutation<Vars>(workspaceId: string | undefined, fn: (vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: agentsKey(workspaceId) }),
  });
}

/** Save a contract; `base` is the version it was read at, for optimistic concurrency. */
export function useSaveAgent(workspaceId: string | undefined) {
  return useAgentMutation(workspaceId, ({ handle, body }: { handle: string; body: Schemas["AgentSave"] }) =>
    unwrap(
      api.PUT("/v1/workspaces/{workspace_id}/agents/{handle}", {
        params: { path: { workspace_id: workspaceId!, handle } },
        body,
      }),
    ),
  );
}

/** Roll an agent back to its shipped contract. */
export function useResetAgent(workspaceId: string | undefined) {
  return useAgentMutation(workspaceId, (handle: string) =>
    unwrap(
      api.DELETE("/v1/workspaces/{workspace_id}/agents/{handle}", {
        params: { path: { workspace_id: workspaceId!, handle } },
      }),
    ),
  );
}
