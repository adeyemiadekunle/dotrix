// The project's `.dotrix/` knowledge: files, their version history, edits, and restores.
// Paths contain slashes (e.g. "architecture/overview.md"), so these calls build the URL
// themselves rather than going through the typed client, which would encode them.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, apiFetch, errorMessage } from "./api";
import type { Scope } from "./issues";

export type FileEntry = Schemas["FileEntry"];
export type FileRead = Schemas["FileRead"];
export type VersionEntry = Schemas["VersionEntry"];
export type VersionRead = Schemas["VersionRead"];
export type VersionDiff = Schemas["VersionDiff"];

const base = (s: Scope) => `/v1/workspaces/${s.workspaceId}/projects/${s.projectId}/knowledge`;
const filePath = (path: string) => path.split("/").map(encodeURIComponent).join("/");

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => undefined));
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const knowledgeKeys = {
  all: (s: Scope) => ["knowledge", s.projectId] as const,
  manifest: (s: Scope) => ["knowledge", s.projectId, "manifest"] as const,
  file: (s: Scope, path: string) => ["knowledge", s.projectId, "file", path] as const,
  versions: (s: Scope, path: string) => ["knowledge", s.projectId, "versions", path] as const,
  version: (s: Scope, path: string, v: number) => ["knowledge", s.projectId, "version", path, v] as const,
  diff: (s: Scope, path: string, v: number) => ["knowledge", s.projectId, "diff", path, v] as const,
};

export function exportUrl(s: Scope): string {
  return `${base(s)}/export`;
}

export function useManifest(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? knowledgeKeys.manifest(scope) : ["knowledge", "none"],
    // "Changes since revision 0" is every file including deleted ones (the plain manifest
    // leaves deletions out), so deleted files can be shown and restored.
    queryFn: () => call<Schemas["Manifest"]>(`${base(scope!)}?since_revision=0`),
    enabled: Boolean(scope),
  });
}

export function useFile(scope: Scope | undefined, path: string | null) {
  return useQuery({
    queryKey: scope && path ? knowledgeKeys.file(scope, path) : ["knowledge", "none"],
    queryFn: () => call<FileRead>(`${base(scope!)}/files/${filePath(path!)}`),
    enabled: Boolean(scope && path),
    retry: false,
  });
}

export function useVersions(scope: Scope | undefined, path: string | null, enabled: boolean) {
  return useQuery({
    queryKey: scope && path ? knowledgeKeys.versions(scope, path) : ["knowledge", "none"],
    queryFn: () => call<VersionEntry[]>(`${base(scope!)}/files/${filePath(path!)}/versions`),
    enabled: Boolean(scope && path) && enabled,
  });
}

export function useVersion(scope: Scope | undefined, path: string | null, version: number | null) {
  return useQuery({
    queryKey: scope && path && version ? knowledgeKeys.version(scope, path, version) : ["knowledge", "none"],
    queryFn: () => call<VersionRead>(`${base(scope!)}/files/${filePath(path!)}/versions/${version}`),
    enabled: Boolean(scope && path && version),
    staleTime: Infinity, // a version never changes
  });
}

export function useVersionDiff(scope: Scope | undefined, path: string | null, version: number | null) {
  return useQuery({
    queryKey: scope && path && version ? knowledgeKeys.diff(scope, path, version) : ["knowledge", "none"],
    queryFn: () => call<VersionDiff>(`${base(scope!)}/files/${filePath(path!)}/versions/${version}/diff`),
    enabled: Boolean(scope && path && version),
    staleTime: Infinity,
  });
}

function useKnowledgeMutation<Vars, Result>(scope: Scope | undefined, fn: (s: Scope, vars: Vars) => Promise<Result>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => fn(scope!, vars),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => (scope ? queryClient.invalidateQueries({ queryKey: knowledgeKeys.all(scope) }) : undefined),
  });
}

export function useWriteFile(scope: Scope | undefined) {
  return useKnowledgeMutation(
    scope,
    (s, { path, content, baseVersion, message }: { path: string; content: string; baseVersion: number | null; message?: string }) =>
      call<FileRead>(`${base(s)}/files/${filePath(path)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, base_version: baseVersion, message: message?.trim() || null }),
      }),
  );
}

export function useDeleteFile(scope: Scope | undefined) {
  return useKnowledgeMutation(scope, (s, { path, baseVersion }: { path: string; baseVersion: number }) =>
    call<void>(`${base(s)}/files/${filePath(path)}?base_version=${baseVersion}`, { method: "DELETE" }),
  );
}

export function useRestoreVersion(scope: Scope | undefined) {
  return useKnowledgeMutation(
    scope,
    (s, { path, version, baseVersion }: { path: string; version: number; baseVersion: number | null }) =>
      call<FileRead>(`${base(s)}/files/${filePath(path)}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version, base_version: baseVersion }),
      }),
  );
}

/** Folders first, then files, alphabetically; built from the flat manifest paths. */
export interface TreeNode {
  name: string;
  path: string;
  children?: TreeNode[];
  file?: FileEntry;
}

export function buildTree(files: FileEntry[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", children: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      if (i === parts.length - 1) {
        node.children!.push({ name: part, path, file });
        return;
      }
      let child = node.children!.find((c) => c.children && c.name === part);
      if (!child) {
        child = { name: part, path, children: [] };
        node.children!.push(child);
      }
      node = child;
    });
  }
  const sort = (nodes: TreeNode[]): TreeNode[] =>
    nodes
      .sort((a, b) => Number(Boolean(b.children)) - Number(Boolean(a.children)) || a.name.localeCompare(b.name))
      .map((n) => (n.children ? { ...n, children: sort(n.children) } : n));
  return sort(root.children!);
}

/** Only owners and admins change how the agents behave. */
export function isAgentRules(path: string): boolean {
  return path === "agent-rules" || path.startsWith("agent-rules/");
}
