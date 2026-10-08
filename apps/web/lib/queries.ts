// Shared queries. Keys are arrays starting with the resource, so a mutation can invalidate
// everything under it (e.g. ["projects", workspaceId]).
import { useQuery } from "@tanstack/react-query";
import { useParams } from "@/lib/navigation";
import { useEffect } from "react";

import { api, unwrap } from "./api";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => unwrap(api.GET("/v1/me")) });
}

export function useWorkspaces() {
  return useQuery({ queryKey: ["workspaces"], queryFn: () => unwrap(api.GET("/v1/workspaces")) });
}

export function useProjects(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["projects", workspaceId],
    queryFn: () =>
      unwrap(api.GET("/v1/workspaces/{workspace_id}/projects", { params: { path: { workspace_id: workspaceId! } } })),
    enabled: Boolean(workspaceId),
  });
}

const LAST_WORKSPACE = "pmagent.lastWorkspace";

export function lastWorkspaceSlug(): string | null {
  try {
    return localStorage.getItem(LAST_WORKSPACE);
  } catch {
    return null;
  }
}

/**
 * The workspace in the URL (/w/[workspace]); on pages outside a workspace (Settings), the one
 * you were last in. Remembered per browser so "/" reopens it.
 */
export function useCurrentWorkspace() {
  const params = useParams<{ workspace?: string }>();
  const workspaces = useWorkspaces();
  const list = workspaces.data ?? [];
  const inUrl = params.workspace ? list.find((w) => w.slug === params.workspace) : undefined;
  const fallback = list.find((w) => w.slug === lastWorkspaceSlug()) ?? list[0];
  // A workspace in the URL that you can't see is "not found"; elsewhere, use the last one.
  const workspace = params.workspace ? inUrl : fallback;

  useEffect(() => {
    if (!params.workspace || !workspace) return;
    try {
      localStorage.setItem(LAST_WORKSPACE, workspace.slug);
    } catch {
      // Storage can be blocked; remembering the workspace is only a convenience.
    }
  }, [params.workspace, workspace]);

  return {
    workspace,
    /** For the sidebar: the URL's workspace, or the last one you were in when that's not found. */
    shown: workspace ?? fallback,
    isLoading: workspaces.isLoading,
    notFound: Boolean(params.workspace) && workspaces.isSuccess && !workspace,
  };
}

/** A project of the current workspace by its id, for pages that choose the project themselves (Chat). */
export function useWorkspaceProject(projectId: string | undefined) {
  const { workspace } = useCurrentWorkspace();
  const projects = useProjects(workspace?.id);
  return { workspace, project: projects.data?.find((p) => p.id === projectId) };
}

/** The project in the URL (/w/[workspace]/p/[project]), by its key. */
export function useCurrentProject() {
  const params = useParams<{ project?: string }>();
  const current = useCurrentWorkspace();
  const { workspace } = current;
  const projects = useProjects(workspace?.id);
  const key = params.project?.toUpperCase();
  const project = projects.data?.find((p) => p.key === key);
  return {
    workspace,
    project,
    isLoading: current.isLoading || projects.isLoading,
    notFound: current.notFound || (projects.isSuccess && !project),
  };
}

/** The project in the URL plus what issue hooks need, and whether you can change things. */
export function useProjectScope() {
  const { workspace, project, isLoading, notFound } = useCurrentProject();
  const scope = workspace && project ? { workspaceId: workspace.id, projectId: project.id } : undefined;
  return { workspace, project, scope, isLoading, notFound, canEdit: Boolean(workspace && workspace.role !== "guest") };
}
