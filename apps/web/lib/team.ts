import type { Schemas } from "@dotrix/api-client";
import { useQueries, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";
import { isActive, type Run } from "./agent";
import type { Scope } from "./issues";

export type AgentActivity = Schemas["AgentActivityRead"];
export type SpecialistTask = Schemas["SpecialistTaskRead"];

export function useBuiltinTeam(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["builtin-team", workspaceId],
    enabled: Boolean(workspaceId),
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/agent-team", { params: { path: { workspace_id: workspaceId! } } })),
  });
}

export function useAgentActivity(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["agent-activity", workspaceId],
    enabled: Boolean(workspaceId),
    refetchInterval: 3000,
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/agent/activity", { params: { path: { workspace_id: workspaceId! } } })),
  });
}

export function useConversationTasks(scope: Scope | undefined, runs: Run[]) {
  return useQueries({
    queries: runs.map((run) => ({
      queryKey: ["specialist-tasks", run.id],
      enabled: Boolean(scope),
      queryFn: () =>
        unwrap(
          api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/tasks", {
            params: { path: { workspace_id: scope!.workspaceId, project_id: scope!.projectId, run_id: run.id } },
          }),
        ),
      refetchInterval: isActive(run) ? 1500 : (false as const),
    })),
  }).flatMap((query) => query.data ?? []);
}

export function useReviewRuns(scope: Scope | undefined, ids: string[]) {
  return useQueries({
    queries: [...new Set(ids)].map((id) => ({
      queryKey: ["review-run", id],
      enabled: Boolean(scope),
      queryFn: () =>
        unwrap(
          api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}", {
            params: { path: { workspace_id: scope!.workspaceId, project_id: scope!.projectId, run_id: id } },
          }),
        ),
      refetchInterval: (query: { state: { data: Run | undefined } }) => (!query.state.data || isActive(query.state.data) ? 1500 : false),
    })),
  }).flatMap((query) => (query.data ? [query.data] : []));
}
