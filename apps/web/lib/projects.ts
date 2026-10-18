// Project writes: create, rename/edit, archive/delete, move to another workspace, members,
// and the connected GitHub repository. Reads live in queries.ts (useProjects and friends);
// starring is in stars.ts.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type Project = Schemas["ProjectRead"];
export type ProjectMember = Schemas["ProjectMemberRead"];
export type ConnectedRepo = Schemas["ConnectedRepoRead"];

const projectPath = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });

function useProjectMutation<Vars>(workspaceId: string | undefined, fn: (vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", workspaceId] });
      void queryClient.invalidateQueries({ queryKey: ["projects", "starred", workspaceId] });
    },
  });
}

export function useCreateProject(workspaceId: string | undefined) {
  return useProjectMutation(workspaceId, (body: Schemas["ProjectCreate"]) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects", {
        params: { path: { workspace_id: workspaceId! } },
        body,
      }),
    ),
  );
}

export function useUpdateProject(scope: Scope | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: Schemas["ProjectUpdate"]) =>
      unwrap(
        api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}", {
          params: { path: projectPath(scope!) },
          body: changes,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: ["projects", scope.workspaceId] });
    },
  });
}

export function useDeleteProject(scope: Scope | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}", {
          params: { path: projectPath(scope!) },
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: ["projects", scope.workspaceId] });
    },
  });
}

/** Move the project to another workspace you own. */
export function useMoveProject(scope: Scope | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ProjectMove"]) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/move", {
          params: { path: projectPath(scope!) },
          body,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

/** Who can see a restricted project (empty = everyone). */
export function useProjectMembers(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? ["project-members", scope.projectId] : ["project-members", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/members", {
          params: { path: projectPath(scope!) },
        }),
      ),
    enabled: Boolean(scope),
  });
}

/** Add or remove a member of a restricted project. */
export function useSetProjectMember(scope: Scope | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, on }: { userId: string; on: boolean }) =>
      on
        ? unwrap(
            api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/members/{user_id}", {
              params: { path: { ...projectPath(scope!), user_id: userId } },
            }),
          )
        : unwrap(
            api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/members/{user_id}", {
              params: { path: { ...projectPath(scope!), user_id: userId } },
            }),
          ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: ["project-members", scope.projectId] });
    },
  });
}

/** The project's connected repository, or null when none. */
export function useRepository(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? ["repository", scope.projectId] : ["repository", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", {
          params: { path: projectPath(scope!) },
        }),
      ),
    enabled: Boolean(scope),
  });
}

function useRepoMutation<Vars>(scope: Scope | undefined, fn: (scope: Scope, vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => fn(scope!, vars),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) void queryClient.invalidateQueries({ queryKey: ["repository", scope.projectId] });
    },
  });
}

/** Connect (or disconnect, with null) the project's GitHub repository. */
export function useConnectRepo(scope: Scope | undefined) {
  return useRepoMutation(scope, (s, body: Schemas["RepoConnect"]) =>
    unwrap(
      api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", {
        params: { path: projectPath(s) },
        body,
      }),
    ),
  );
}

export function useDisconnectRepo(scope: Scope | undefined) {
  return useRepoMutation(scope, (s) =>
    unwrap(
      api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", {
        params: { path: projectPath(s) },
      }),
    ),
  );
}

/** Fetch the repository now rather than waiting for the sync job. */
export function useSyncRepository(scope: Scope | undefined) {
  return useRepoMutation(scope, (s) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/sync", {
        params: { path: projectPath(s) },
      }),
    ),
  );
}
