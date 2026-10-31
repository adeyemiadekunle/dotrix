import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "@/lib/api";
import type { Scope } from "@/lib/issues";
import { desktop } from "@/src/core/desktop";

export type CodingRun = Schemas["CodingRunRead"];
export type CodingRunStatus = Schemas["CodingRunStatus"];
export type CodingSession = Schemas["CodingSessionRead"];
export type PrState = Schemas["PrState"];
type ApprovalMode = NonNullable<Schemas["CodingRunCreate"]["approval_mode"]>;

const path = (scope: Scope) => ({ workspace_id: scope.workspaceId, project_id: scope.projectId });
const runsKey = (scope: Scope | undefined, issueKey?: string | null) => ["coding-runs", scope?.projectId, issueKey];

export const AGENT_NAMES: Record<Schemas["CodingAgent"], string> = { "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode", fx: "fx" };

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

/** A turn's status in words, saying where a local one waits. */
export function statusLabel(run: Pick<CodingRun, "status" | "location" | "runner_name">): string {
  if (run.location === "local" && run.status === "queued") return "Waiting for your computer";
  if (run.location === "local" && run.status === "running") return `Coding on ${run.runner_name ?? "your computer"}`;
  return STATUS_LABELS[run.status];
}

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

export type CodingLocation = Schemas["CodingLocation"];

/** Ask Kai to code an issue: on the platform (`cloud`) or on your own computer (`local`, through `dotrix runner`). */
export function useStartCoding(
  scope: Scope | undefined,
  issueKey: string,
  approvalMode: ApprovalMode | null = null,
  location: CodingLocation = "cloud",
  agent: Schemas["CodingAgent"] | null = null,
  model: string | null = null,
) {
  return useCodingMutation(scope, issueKey, (s, note: string | null) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/issues/{key}/runs", {
        params: { path: { ...path(s), key: issueKey } },
        body: { note, approval_mode: approvalMode, location, agent, model },
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

/** Delete a session's cloud sandbox (warm or asleep); the session stays and its next turn starts fresh. */
export function useDeleteSandbox(scope: Scope | undefined, sessionId: string, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, _: void) =>
    unwrap(
      api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/sessions/{session_id}/sandbox", { params: { path: sessionPath(s, sessionId) } }),
    ),
  );
}

export function useDeleteSession(scope: Scope | undefined, sessionId: string, issueKey: string) {
  return useCodingMutation(scope, issueKey, (s, _: void) =>
    unwrap(api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/sessions/{session_id}", { params: { path: sessionPath(s, sessionId) } })),
  );
}

export type CodingTree = Schemas["CodingTree"];
export type CodingFile = Schemas["CodingFile"];
type CodingEventRead = Schemas["CodingEventRead"];

const ACTIVE_TURN: CodingRunStatus[] = ["queued", "running"];

/** A turn's changes as a unified diff (the panel's Changes); refreshed while the turn works. */
export function useCodingDiff(scope: Scope | undefined, run: Pick<CodingRun, "id" | "status"> | undefined) {
  return useQuery({
    // The status in the key: when the turn moves on (finished, changes ready), the diff is fetched once more.
    queryKey: ["coding-run", scope?.projectId, run?.id, "diff", run?.status],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/diff", {
          params: { path: { ...path(scope!), coding_run_id: run!.id } },
        }),
      ),
    enabled: Boolean(scope && run),
    placeholderData: (previous, query) => (query?.queryKey[2] === run?.id ? previous : undefined), // the same turn's, while its next status loads
    refetchInterval: run && ACTIVE_TURN.includes(run.status) ? 5_000 : false,
  });
}

/** Every file as a turn leaves the repository (the panel's Files). */
export function useCodingTree(
  scope: Scope | undefined,
  run: Pick<CodingRun, "id" | "status" | "base_sha"> | undefined,
  enabled: boolean,
  worktree: string | null = null,
) {
  // A turn coding on this computer (the desktop app): its worktree as it is now, read every few seconds.
  const here = worktree ? desktop() : null;
  return useQuery<CodingTree>({
    queryKey: ["coding-run", scope?.projectId, run?.id, "tree", run?.status, worktree],
    queryFn: async () =>
      here
        ? { base_sha: run!.base_sha ?? "", ...(await here.worktree.tree(worktree!)) }
        : unwrap(
            api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/tree", {
              params: { path: { ...path(scope!), coding_run_id: run!.id } },
            }),
          ),
    enabled: Boolean(scope && run?.base_sha) && enabled,
    retry: false,
    staleTime: here ? 0 : 30_000,
    refetchInterval: here && run?.status === "running" ? 3000 : false,
  });
}

/** One file before a turn and after it (on this computer: in its worktree, as it is now). */
export function useCodingFile(scope: Scope | undefined, runId: string | undefined, filePath: string | null, worktree: string | null = null) {
  const here = worktree ? desktop() : null;
  return useQuery<CodingFile>({
    queryKey: ["coding-run", scope?.projectId, runId, "file", filePath, worktree],
    queryFn: () =>
      here
        ? here.worktree.file(worktree!, filePath!)
        : unwrap(
            api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/file", {
              params: { path: { ...path(scope!), coding_run_id: runId! }, query: { path: filePath! } },
            }),
          ),
    enabled: Boolean(scope && runId && filePath),
    retry: false,
    staleTime: here ? 0 : 30_000,
    refetchInterval: here ? 3000 : false,
  });
}

/** Every event of a turn (its commands and their output, for the panel's Terminal), refreshed while it works. */
export function useCodingEvents(scope: Scope | undefined, run: Pick<CodingRun, "id" | "status"> | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["coding-run", scope?.projectId, run?.id, "events", run?.status],
    queryFn: async () => {
      const all: CodingEventRead[] = [];
      let after = -1;
      for (let page = 0; page < 10; page++) {
        const got = await unwrap(
          api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/events", {
            params: { path: { ...path(scope!), coding_run_id: run!.id }, query: { after, limit: 500 } },
          }),
        );
        all.push(...got.events);
        if (got.next == null) break;
        after = got.next;
      }
      return all;
    },
    enabled: Boolean(scope && run) && enabled,
    placeholderData: (previous, query) => (query?.queryKey[2] === run?.id ? previous : undefined), // the same turn's, while its next status loads
    refetchInterval: run && ACTIVE_TURN.includes(run.status) ? 2_000 : false,
  });
}
