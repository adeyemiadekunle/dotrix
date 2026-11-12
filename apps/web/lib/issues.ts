// Issue queries and mutations. Every key starts with ["issues", projectId] so one invalidation
// refreshes the board, backlog, epics, and any open issue after a change.
import type { Schemas } from "@dotrix/api-client";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
export type Issue = Schemas["IssueRead"];
type IssueStatus = Schemas["IssueStatus"];
type IssueType = Schemas["IssueType"];

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

/** Every issues query a change in this project can show up in: the project's own and the workspace-wide lists. */
export const issueQueriesOf = (s: Scope) => [issueKeys.all(s), ["issues", "workspace", s.workspaceId] as const] as const;

/** Filters for issues across the workspace's projects; `me` stands for you. */
export interface WorkspaceIssueFilters {
  type?: IssueType[];
  assignee?: string;
  reporter?: string;
  watching?: boolean;
  starred?: boolean;
  archived?: "exclude" | "include" | "only";
  status?: IssueStatus[];
  label?: string;
  due_before?: string;
  order?: "due" | "priority" | "created" | "updated";
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

/** The issue-detail query as options, so module code (live.ts) can prefetch the same cache entry. */
export const issueOptions = (s: Scope, key: string) => ({
  queryKey: issueKeys.issue(s, key),
  queryFn: () =>
    unwrap(
      api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/issues/{key}", {
        params: { path: { ...path(s), key } },
      }),
    ),
  retry: false,
  // The drawer, Inbox preview and comment helpers read this entry synchronously — keep it for the
  // session like the store's D().comments copy did, or badges/counts drop to 0. Bounded would
  // re-open that gap until the API rows carry a comment_count like attachment_count (follow-up).
  gcTime: Infinity,
});

export function useIssue(scope: Scope | undefined, key: string | null) {
  return useQuery({
    queryKey: scope && key ? issueKeys.issue(scope, key) : ["issues", "none"],
    queryFn: () => (scope && key ? issueOptions(scope, key).queryFn() : Promise.resolve(undefined)),
    enabled: Boolean(scope && key),
    retry: false,
    gcTime: Infinity,
  });
}

/**
 * Refresh everything issue-shaped in the project, the lists across projects (Home, My issues,
 * Tasks), and the activity feeds; show the API's reason when it says no.
 */
function useIssueMutation<Vars, Result = unknown>(scope: Scope | undefined, fn: (scope: Scope, vars: Vars) => Promise<Result>) {
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

export function useCreateIssue(scope: Scope | undefined) {
  return useIssueMutation(scope, (s, body: Schemas["IssueCreate"]) =>
    unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/issues", { params: { path: path(s) }, body })),
  );
}
