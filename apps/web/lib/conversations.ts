// Conversations across projects (or about none): read-only, private to whoever started them.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { isActive, type Run, type RunStreamState } from "@/lib/agent";
import { api, ensureSession, errorMessage, unwrap } from "@/lib/api";

export type CrossConversation = Schemas["WorkspaceConversation"];

const POLL_MS = 1500;
const keys = {
  list: (workspaceId: string | undefined) => ["conversations", workspaceId] as const,
  thread: (workspaceId: string | undefined, threadId: string) => ["conversations", workspaceId, "thread", threadId] as const,
};

export function useCrossConversations(workspaceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.list(workspaceId),
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/conversations", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: Boolean(workspaceId) && enabled,
    refetchInterval: 20_000,
  });
}

/** One conversation across projects, oldest first, polled while it's answering. */
export function useCrossThread(workspaceId: string | undefined, threadId: string | null) {
  return useQuery({
    queryKey: workspaceId && threadId ? keys.thread(workspaceId, threadId) : ["conversations", "none"],
    queryFn: async (): Promise<Run[]> => {
      const runs = await unwrap(
        api.GET("/v1/workspaces/{workspace_id}/conversations/runs", {
          params: { path: { workspace_id: workspaceId! }, query: { thread_id: threadId! } },
        }),
      );
      return runs.slice().reverse();
    },
    enabled: Boolean(workspaceId && threadId),
    refetchInterval: (query) => ((query.state.data ?? []).some(isActive) ? POLL_MS : false),
  });
}

export function useSendCross(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["WorkspaceRunCreate"]) =>
      unwrap(api.POST("/v1/workspaces/{workspace_id}/conversations/runs", { params: { path: { workspace_id: workspaceId! } }, body })),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] }),
  });
}

export function useStopCross(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/conversations/runs/{run_id}/stop", {
          params: { path: { workspace_id: workspaceId!, run_id: runId } },
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] }),
  });
}

/** The reply as it's written (the same events as a project's runs). */
export function useCrossStream(workspaceId: string | undefined, runId: string, active: boolean): RunStreamState {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [activity, setActivity] = useState<string | null>(null);
  useEffect(() => {
    if (!workspaceId || !active) return;
    let source: EventSource | undefined;
    let closed = false;
    // An EventSource can't refresh an expired session itself: check it's current first.
    void ensureSession().then(() => {
      if (closed) return;
      source = new EventSource(`/v1/workspaces/${workspaceId}/conversations/runs/${runId}/stream`);
      const stream = source;
      const read = (event: MessageEvent) => (JSON.parse(event.data) as { text: string }).text;
      stream.addEventListener("text", (e) => setText(read(e as MessageEvent)));
      stream.addEventListener("delta", (e) => setText((t) => t + read(e as MessageEvent)));
      stream.addEventListener("activity", (e) => setActivity(read(e as MessageEvent)));
      stream.addEventListener("end", () => {
        stream.close();
        setActivity(null);
        void queryClient.invalidateQueries({ queryKey: ["conversations", workspaceId] });
      });
      stream.onerror = () => stream.close();
    });
    return () => {
      closed = true;
      source?.close();
    };
  }, [workspaceId, runId, active, queryClient]);
  return { text, activity };
}
