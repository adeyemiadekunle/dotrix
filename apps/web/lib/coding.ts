import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "@/lib/api";
import type { Scope } from "@/lib/issues";

export type CodingRun = Schemas["CodingRunRead"];
export type CodingRunStatus = Schemas["CodingRunStatus"];
export type CodingSession = Schemas["CodingSessionRead"];
export type PrState = Schemas["PrState"];
type ApprovalMode = NonNullable<Schemas["CodingRunCreate"]["approval_mode"]>;

const path = (scope: Scope) => ({ workspace_id: scope.workspaceId, project_id: scope.projectId });
const runsKey = (scope: Scope | undefined, issueKey?: string | null) => ["coding-runs", scope?.projectId, issueKey];

export const AGENT_NAMES: Record<Schemas["CodingAgent"], string> = { "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode" };

export const STATUS_LABELS: Record<CodingRunStatus, string> = {
  awaiting_approval: "Waiting for approval",
  rejected: "Rejected",
  queued: "Starting",
  running: "Coding",
  changes_ready: "Changes ready",
  pr_opened: "PR opened",
  no_changes: "No changes",
  failed: "Failed",
  recovery_required: "Needs recovery",
  stopped: "Stopped",
};

export const PR_LABELS: Record<PrState, string> = { open: "Open", merged: "Merged", closed: "Closed" };

/** Where a session opens: Chat's Coding tab. */
export function sessionHref(workspaceSlug: string, projectKey: string, sessionId: string): string {
  return `/w/${workspaceSlug}/chat?tab=coding&project=${projectKey}&session=${sessionId}`;
}

const ACTIVE: CodingRunStatus[] = ["awaiting_approval", "queued", "running", "changes_ready"];
export const isActive = (run: Pick<CodingRun, "status">) => ACTIVE.includes(run.status);

/** Whether this project's issues can be coded here, and by which tool. */
export function useCodingAvailability(scope: Scope | undefined) {
  return useQuery({
    queryKey: ["coding", scope?.projectId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding", { params: { path: path(scope!) } })),
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
    refetchInterval: (query) => pace(query.state.data),
  });
}

function useCodingMutation<T, R = CodingRun>(scope: Scope | undefined, issueKey: string, fn: (scope: Scope, arg: T) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (arg: T) => fn(scope!, arg),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["coding-runs", scope?.projectId] });
      void queryClient.invalidateQueries({ queryKey: ["coding-sessions"] });
      void queryClient.invalidateQueries({ queryKey: ["coding-session", scope?.projectId] });
      void queryClient.invalidateQueries({ queryKey: ["coding-run", scope?.projectId] });
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
      // Approving assigns the issue to the coding tool and moves it to in progress.
      void queryClient.invalidateQueries({ queryKey: ["issues", scope?.projectId] });
    },
  });
}

export function useStartCoding(scope: Scope | undefined, issueKey: string, approvalMode: ApprovalMode | null = null) {
  return useCodingMutation(scope, issueKey, (s, note: string | null) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/issues/{key}/runs", {
        params: { path: { ...path(s), key: issueKey } },
        body: { note, approval_mode: approvalMode },
      }),
    ),
  );
}

export function useDecideCoding(scope: Scope | undefined, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, { runId, decision, reason }: { runId: string; decision: "approve" | "reject"; reason?: string | null }) =>
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

/** Undo a pushed turn: a new turn whose commit reverts it on the session's branch (approved like any turn). */
export function useRevertCoding(scope: Scope | undefined, issueKey: string, approvalMode: ApprovalMode | null = null) {
  return useCodingMutation(scope, issueKey, (s, runId: string) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/revert", {
        params: { path: { ...path(s), coding_run_id: runId } },
        body: { approval_mode: approvalMode },
      }),
    ),
  );
}

/** Settle a run whose outcome is uncertain: check GitHub (adopt or open its PR, or run the turn again), or discard it. */
export function useRecoverCoding(scope: Scope | undefined, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, { runId, action }: { runId: string; action: "check" | "discard" }) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/recover", {
        params: { path: { ...path(s), coding_run_id: runId } },
        body: { action },
      }),
    ),
  );
}

/** A run's refresh pace: quick while it works, slower while it waits for a decision. */
function pace(runs: Pick<CodingRun, "status">[] | undefined): number | false {
  if (!runs?.some(isActive)) return false;
  return runs.some((r) => r.status === "running" || r.status === "queued") ? 2_000 : 10_000;
}

/** The workspace's coding sessions (Chat's Coding tab), latest activity first. */
export function useCodingSessions(workspaceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["coding-sessions", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/coding/sessions", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: Boolean(workspaceId) && enabled,
    refetchOnMount: "always",
    refetchInterval: (query) => (query.state.data?.some(isActive) ? 5_000 : false),
  });
}

/** A session's turns, first to latest; polled while one waits or works. */
export function useCodingSession(scope: Scope | undefined, sessionId: string | null | undefined) {
  return useQuery({
    queryKey: ["coding-session", scope?.projectId, sessionId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/sessions/{session_id}", {
          params: { path: { ...path(scope!), session_id: sessionId! } },
        }),
      ),
    enabled: Boolean(scope && sessionId),
    refetchOnMount: "always",
    refetchInterval: (query) => pace(query.state.data),
  });
}

/** One run (a notification's coding approval). */
export function useCodingRun(scope: Scope | undefined, runId: string | null | undefined) {
  return useQuery({
    queryKey: ["coding-run", scope?.projectId, runId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}", {
          params: { path: { ...path(scope!), coding_run_id: runId! } },
        }),
      ),
    enabled: Boolean(scope && runId),
    refetchOnMount: "always",
    refetchInterval: (query) => pace(query.state.data ? [query.state.data] : undefined),
  });
}

/** Another turn in a session: the same agent, on its branch and PR. */
export function useFollowUp(scope: Scope | undefined, sessionId: string, issueKey: string, approvalMode: ApprovalMode | null = null) {
  return useCodingMutation(scope, issueKey, (s, message: string) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/sessions/{session_id}/turns", {
        params: { path: { ...path(s), session_id: sessionId } },
        body: { message, approval_mode: approvalMode },
      }),
    ),
  );
}

const sessionPath = (s: Scope, sessionId: string) => ({ ...path(s), session_id: sessionId });

/** Rename, pin, or archive a session. */
export function useUpdateSession(scope: Scope | undefined, sessionId: string, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, body: Schemas["CodingSessionUpdate"]) =>
    unwrap(
      api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/sessions/{session_id}", { params: { path: sessionPath(s, sessionId) }, body }),
    ),
  );
}

/** Close a session: no more turns on its branch. */
export function useCloseSession(scope: Scope | undefined, sessionId: string, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, _: void) =>
    unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/sessions/{session_id}/close", { params: { path: sessionPath(s, sessionId) } })),
  );
}

export function useDeleteSession(scope: Scope | undefined, sessionId: string, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, _: void) =>
    unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/sessions/{session_id}", { params: { path: sessionPath(s, sessionId) } })),
  );
}
