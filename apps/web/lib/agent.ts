"use client";

// Talking to the project's agents. A conversation is a thread of runs: each run is one message
// to the PM and its outcome (a reply, a failure, or actions waiting for approval). Runs work in
// the background, so active ones are polled until they finish or pause.
import type { Schemas } from "@pmagent/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type Run = Schemas["AgentRunRead"];
export type Approval = Schemas["ApprovalRead"];
export type WorkspaceApproval = Schemas["WorkspaceApprovalRead"];
export type Decision = Schemas["Decision"];

export const isActive = (run: Pick<Run, "status">) => run.status === "queued" || run.status === "running";

// Kept in sync with ARCHITECTURE_DRAFT_PROMPT in the backend's agents service.
const ARCHITECTURE_PROMPT_START = "Project setup: draft the architecture overview.";

/** How a run is named in lists: its message, or what a built-in request was for. */
export function runTitle(run: Pick<Run, "kind" | "message">): string {
  if (run.kind === "briefing") return "Daily briefing";
  if (run.message.startsWith(ARCHITECTURE_PROMPT_START)) return "Draft the architecture overview";
  return run.message;
}

const path = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });
const POLL_MS = 1500;
const WAITING_POLL_MS = 5000;

export const agentKeys = {
  project: (s: Scope) => ["agent", s.projectId] as const,
  thread: (s: Scope, threadId: string) => ["agent", s.projectId, "thread", threadId] as const,
  recent: (s: Scope) => ["agent", s.projectId, "recent"] as const,
  workspaceApprovals: (workspaceId: string) => ["approvals", workspaceId] as const,
};

/** One conversation, oldest first, polled while the PM is working. */
export function useThread(scope: Scope | undefined, threadId: string | null) {
  return useQuery({
    queryKey: scope && threadId ? agentKeys.thread(scope, threadId) : ["agent", "none"],
    queryFn: async () => {
      const runs = await unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs", {
          params: { path: path(scope!), query: { thread_id: threadId!, limit: 100 } },
        }),
      );
      return runs.slice().reverse();
    },
    enabled: Boolean(scope && threadId),
    // Fast while the PM works; slower while it waits, since the decision may come from
    // someone else (or another tab) and the run then resumes.
    refetchInterval: (query) => {
      const runs = query.state.data ?? [];
      if (runs.some(isActive)) return POLL_MS;
      return runs.some((r) => r.status === "awaiting_approval") ? WAITING_POLL_MS : false;
    },
  });
}

export interface ThreadSummary {
  threadId: string;
  title: string;
  kind: Run["kind"];
  updatedAt: string;
  waiting: boolean;
}

/** Recent conversations, newest activity first (grouped from recent runs). */
export function useRecentThreads(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? agentKeys.recent(scope) : ["agent", "none"],
    queryFn: async (): Promise<ThreadSummary[]> => {
      const runs = await unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs", {
          params: { path: path(scope!), query: { limit: 100 } },
        }),
      );
      const threads = new Map<string, ThreadSummary>();
      // Newest first: the first run seen sets the activity time; the oldest names the thread.
      for (const run of runs) {
        const known = threads.get(run.thread_id);
        threads.set(run.thread_id, {
          threadId: run.thread_id,
          title: runTitle(run),
          kind: run.kind,
          updatedAt: known?.updatedAt ?? run.updated_at,
          waiting: (known?.waiting ?? false) || run.status === "awaiting_approval",
        });
      }
      return [...threads.values()];
    },
    enabled: Boolean(scope),
  });
}

function useAgentMutation<Vars>(scope: Scope | undefined, fn: (scope: Scope, vars: Vars) => Promise<Run>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => fn(scope!, vars),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: async () => {
      if (!scope) return;
      await queryClient.invalidateQueries({ queryKey: agentKeys.project(scope) });
      await queryClient.invalidateQueries({ queryKey: ["approvals", scope.workspaceId] });
      // Approved actions may have changed issues or files.
      await queryClient.invalidateQueries({ queryKey: ["issues", scope.projectId] });
    },
  });
}

export function useSendMessage(scope: Scope | undefined) {
  return useAgentMutation(scope, (s, { message, threadId }: { message: string; threadId: string | null }) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs", {
        params: { path: path(s) },
        body: { message, thread_id: threadId },
      }),
    ),
  );
}

export function useBriefing(scope: Scope | undefined) {
  return useAgentMutation(scope, (s, _: void) =>
    unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/briefing", { params: { path: path(s) } })),
  );
}

export function useArchitectureDraft(scope: Scope | undefined) {
  return useAgentMutation(scope, (s, _: void) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/architecture-draft", {
        params: { path: path(s) },
        body: { repo_summary: null },
      }),
    ),
  );
}

export function useDecide(scope: Scope | undefined) {
  return useAgentMutation(scope, (s, { runId, decisions }: { runId: string; decisions: Decision[] }) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/decisions", {
        params: { path: { ...path(s), run_id: runId } },
        body: { decisions },
      }),
    ),
  );
}

/** Everything waiting for a decision in the workspace (sidebar count and the approvals page). */
export function useWorkspaceApprovals(workspaceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: workspaceId ? agentKeys.workspaceApprovals(workspaceId) : ["approvals", "none"],
    queryFn: () =>
      unwrap(api.GET("/v1/workspaces/{workspace_id}/approvals", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: Boolean(workspaceId) && enabled,
    refetchInterval: 20_000,
  });
}
