// Issue queries and mutations. Every key starts with ["issues", projectId] so one invalidation
// refreshes the board, backlog, epics, and any open issue after a change.
import type { Schemas } from "@dotrix/api-client";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";

export type IssueSummary = Schemas["IssueSummary"];
export type Issue = Schemas["IssueRead"];
export type IssueStatus = Schemas["IssueStatus"];
export type IssueType = Schemas["IssueType"];
export type Priority = Schemas["Priority"];
export type AgentAssignee = Schemas["AgentAssignee"];
export type Board = Schemas["Board"];

export interface Scope {
  workspaceId: string;
  projectId: string;
}

export interface BoardFilters {
  type?: IssueType[];
  assignee?: string;
  label?: string;
  epic?: string;
}

const path = ({ workspaceId, projectId }: Scope) => ({ workspace_id: workspaceId, project_id: projectId });

export const issueKeys = {
  all: (s: Scope) => ["issues", s.projectId] as const,
  board: (s: Scope, f: BoardFilters) => ["issues", s.projectId, "board", f] as const,
  backlog: (s: Scope) => ["issues", s.projectId, "backlog"] as const,
  epics: (s: Scope) => ["issues", s.projectId, "epics"] as const,
  issue: (s: Scope, key: string) => ["issues", s.projectId, "issue", key] as const,
};

export type WorkspaceIssue = Schemas["WorkspaceIssue"];

/** Filters for issues across the workspace's projects; `me` stands for you. */
export interface WorkspaceIssueFilters {
  assignee?: string;
  reporter?: string;
  watching?: boolean;
  status?: IssueStatus[];
}

/** Issues in every project of the workspace you can see (Home, My issues). */
export function useWorkspaceIssues(workspaceId: string | undefined, filters: WorkspaceIssueFilters) {
  return useQuery({
    queryKey: ["issues", "workspace", workspaceId, filters],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/issues", {
          params: { path: { workspace_id: workspaceId! }, query: { ...filters, limit: 5000 } },
        }),
      ),
    enabled: Boolean(workspaceId),
    placeholderData: keepPreviousData,
  });
}

/** Every issue in the project, done ones too, in backlog order (the Table). */
export function useAllIssues(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? [...issueKeys.all(scope), "all"] : ["issues", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", {
          params: { path: path(scope!), query: { order: "rank", limit: 5000 } },
        }),
      ),
    enabled: Boolean(scope),
  });
}

export function useBoard(scope: Scope | undefined, filters: BoardFilters) {
  return useQuery({
    queryKey: scope ? issueKeys.board(scope, filters) : ["issues", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/board", {
          params: {
            path: path(scope!),
            query: {
              type: filters.type?.length ? filters.type : undefined,
              assignee: filters.assignee || undefined,
              label: filters.label || undefined,
              epic: filters.epic || undefined,
            },
          },
        }),
      ),
    enabled: Boolean(scope),
    placeholderData: (previous) => previous, // keep the board on screen while filters change
  });
}

export function useBacklog(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? issueKeys.backlog(scope) : ["issues", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/backlog", {
          params: { path: path(scope!), query: { limit: 2000 } },
        }),
      ),
    enabled: Boolean(scope),
  });
}

export function useEpics(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? issueKeys.epics(scope) : ["issues", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/epics", {
          params: { path: path(scope!) },
        }),
      ),
    enabled: Boolean(scope),
  });
}

/** `value`, once it has stopped changing for `ms`. */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

/** Existing issues like the one being written (by keywords and, when the server has an
 * embedding model, by meaning), to catch duplicates before they're created. */
export function useSimilarIssues(scope: Scope | undefined, text: string) {
  const query = useDebounced(text.trim(), 400);
  return useQuery({
    queryKey: scope ? ["issues", scope.projectId, "similar", query] : ["issues", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/search", {
          params: { path: path(scope!), query: { q: query, source: "issue", limit: 3 } },
        }),
      ),
    enabled: Boolean(scope) && query.length >= 4,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useIssue(scope: Scope | undefined, key: string | null) {
  return useQuery({
    queryKey: scope && key ? issueKeys.issue(scope, key) : ["issues", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", {
          params: { path: { ...path(scope!), key: key! } },
        }),
      ),
    enabled: Boolean(scope && key),
    retry: false,
  });
}

export function useMembers(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["members", workspaceId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/members", { params: { path: { workspace_id: workspaceId! } } }),
      ),
    enabled: Boolean(workspaceId),
    staleTime: 5 * 60_000,
  });
}

/**
 * Refresh everything issue-shaped in the project, the lists across projects (Home, My issues,
 * Tasks), and the activity feeds; show the API's reason when it says no.
 */
function useIssueMutation<Vars>(scope: Scope | undefined, fn: (scope: Scope, vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => fn(scope!, vars),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: async () => {
      if (!scope) return;
      await queryClient.invalidateQueries({ queryKey: issueKeys.all(scope) });
      await queryClient.invalidateQueries({ queryKey: ["issues", "workspace", scope.workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["activity"] });
    },
  });
}

export function useUpdateIssue(scope: Scope | undefined) {
  return useIssueMutation(scope, (s, { key, changes }: { key: string; changes: Schemas["IssueUpdate"] }) =>
    unwrap(
      api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", {
        params: { path: { ...path(s), key } },
        body: changes,
      }),
    ),
  );
}

/** Change an issue in any project of the workspace (lists across projects, the workspace Timeline). */
export function useUpdateAnyIssue(workspaceId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, key, changes }: { projectId: string; key: string; changes: Schemas["IssueUpdate"] }) =>
      unwrap(
        api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", {
          params: { path: { workspace_id: workspaceId!, project_id: projectId, key } },
          body: changes,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: async (_data, _error, { projectId }) => {
      await queryClient.invalidateQueries({ queryKey: ["issues", "workspace", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["issues", projectId] });
    },
  });
}

export function useCreateIssue(scope: Scope | undefined) {
  return useIssueMutation(scope, (s, body: Schemas["IssueCreate"]) =>
    unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", { params: { path: path(s) }, body })),
  );
}

export function useComment(scope: Scope | undefined) {
  return useIssueMutation(scope, (s, { key, body, mentions = [] }: { key: string; body: string; mentions?: string[] }) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/comments", {
        params: { path: { ...path(s), key } },
        body: { body, mentions },
      }),
    ),
  );
}

export function useWatch(scope: Scope | undefined) {
  return useIssueMutation(scope, (s, { key, watch }: { key: string; watch: boolean }) => {
    const params = { path: { ...path(s), key } };
    return unwrap(
      watch
        ? api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/watch", { params })
        : api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/watch", { params }),
    );
  });
}

export type RankTarget = { before: string } | { after: string };

/** Move an issue (optionally to another status) and put it next to a neighbour in rank order. */
export function useMoveIssue(scope: Scope | undefined) {
  return useIssueMutation(
    scope,
    async (s, { key, status, rank }: { key: string; status?: IssueStatus; rank?: RankTarget }) => {
      const params = { path: { ...path(s), key } };
      if (status) {
        await unwrap(
          api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", { params, body: { status } }),
        );
      }
      if (rank) {
        await unwrap(
          api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}/rank", { params, body: rank }),
        );
      }
    },
  );
}
