"use client";

import type { Schemas } from "@pmagent/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "@/lib/api";
import type { Scope } from "@/lib/issues";

export type CodingRun = Schemas["CodingRunRead"];
export type CodingRunStatus = Schemas["CodingRunStatus"];

const path = (scope: Scope) => ({ workspace_id: scope.workspaceId, project_id: scope.projectId });
const runsKey = (scope: Scope | undefined, issueKey?: string | null) => ["coding-runs", scope?.projectId, issueKey];

export const AGENT_NAMES: Record<Schemas["CodingAgent"], string> = { "claude-code": "Claude Code", codex: "Codex" };

export const STATUS_LABELS: Record<CodingRunStatus, string> = {
  awaiting_approval: "Waiting for approval",
  rejected: "Rejected",
  queued: "Starting",
  running: "Coding",
  pr_opened: "PR opened",
  no_changes: "No changes",
  failed: "Failed",
  stopped: "Stopped",
};

const ACTIVE: CodingRunStatus[] = ["awaiting_approval", "queued", "running"];
export const isActive = (run: Pick<CodingRun, "status">) => ACTIVE.includes(run.status);

/** Whether this project's issues can be coded here, and by which tool. */
export function useCodingAvailability(scope: Scope | undefined) {
  return useQuery({
    queryKey: ["coding", scope?.projectId],
    queryFn: () =>
      unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding", { params: { path: path(scope!) } })),
    enabled: Boolean(scope),
    staleTime: 60_000,
  });
}

/** One issue's coding runs, newest first; polled while one waits or works. */
export function useCodingRuns(scope: Scope | undefined, issueKey: string | null | undefined) {
  return useQuery({
    queryKey: runsKey(scope, issueKey),
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs", {
          params: { path: path(scope!), query: { issue: issueKey! } },
        }),
      ),
    enabled: Boolean(scope && issueKey),
    refetchOnMount: "always",
    refetchInterval: (query) => {
      const runs = query.state.data;
      if (!runs?.some(isActive)) return false;
      return runs.some((r) => r.status === "running" || r.status === "queued") ? 2_000 : 10_000;
    },
  });
}

function useCodingMutation<T>(scope: Scope | undefined, issueKey: string, fn: (scope: Scope, arg: T) => Promise<CodingRun>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (arg: T) => fn(scope!, arg),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: runsKey(scope, issueKey) });
      // Approving assigns the issue to the coding tool and moves it to in progress.
      void queryClient.invalidateQueries({ queryKey: ["issues", scope?.projectId] });
    },
  });
}

export function useStartCoding(scope: Scope | undefined, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, note: string | null) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/issues/{key}/runs", {
        params: { path: { ...path(s), key: issueKey } },
        body: { note },
      }),
    ),
  );
}

export function useDecideCoding(scope: Scope | undefined, issueKey: string) {
  return useCodingMutation(
    scope,
    issueKey,
    (s, { runId, decision, reason }: { runId: string; decision: "approve" | "reject"; reason?: string | null }) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/decision", {
          params: { path: { ...path(s), coding_run_id: runId } },
          body: { decision, reason: reason || null },
        }),
      ),
  );
}

export function useStopCoding(scope: Scope | undefined, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, runId: string) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/stop", {
        params: { path: { ...path(s), coding_run_id: runId } },
      }),
    ),
  );
}
