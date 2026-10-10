import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { ApiError, api, apiFetch, errorMessage, unwrap } from "./api";

export type Document = Schemas["DocumentRead"];

/** What the backend converts to Markdown (dotrix_engine.ingest.SUPPORTED_EXTENSIONS). */
export const DOCUMENT_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".xls",
  ".html",
  ".htm",
  ".csv",
  ".json",
  ".xml",
  ".md",
  ".markdown",
  ".txt",
  ".rst",
];
/** The backend's default limit (DOTRIX_MAX_UPLOAD_MB); it has the final say. */
export const MAX_UPLOAD_MB = 25;

export function checkFile(file: File): string | null {
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!DOCUMENT_EXTENSIONS.includes(ext)) return `${ext || "Files without an extension"} can't be imported`;
  if (file.size > MAX_UPLOAD_MB * 1_000_000) return `Larger than ${MAX_UPLOAD_MB} MB`;
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1_000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${Math.round(bytes / 1_000)} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

const documentsPath = (workspaceId: string, projectId: string) =>
  `/v1/workspaces/${workspaceId}/projects/${projectId}/documents`;

export function originalUrl(workspaceId: string, projectId: string, documentId: string): string {
  return `${documentsPath(workspaceId, projectId)}/${documentId}/original`;
}

export function useDocuments(scope: { workspaceId: string; projectId: string } | undefined) {
  return useQuery({
    queryKey: ["documents", scope?.projectId],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/documents", {
          params: { path: { workspace_id: scope!.workspaceId, project_id: scope!.projectId } },
        }),
      ),
    enabled: Boolean(scope),
    // Uploads are converted in the background: check back until they're done.
    refetchInterval: (query) => ((query.state.data ?? []).some((d) => d.status === "converting") ? 2000 : false),
  });
}

/** One multipart upload to the API; the backend stores the original and converts it. */
async function uploadOne(workspaceId: string, projectId: string, file: File): Promise<Document> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await apiFetch(documentsPath(workspaceId, projectId), { method: "POST", body: form });
  if (!response.ok) {
    throw new ApiError(response.status, await response.json().catch(() => undefined));
  }
  return (await response.json()) as Document;
}

export type UploadState = { file: File; status: "queued" | "uploading" | "done" | "error"; error?: string };

/** Upload files one at a time (conversion is heavy), tracking each file's state. */
export function useUploads() {
  const queryClient = useQueryClient();
  const [uploads, setUploads] = useState<UploadState[]>([]);

  const upload = useCallback(
    async (workspaceId: string, projectId: string, files: File[]) => {
      const start = files.map((file): UploadState => ({ file, status: "queued" }));
      setUploads(start);
      const set = (i: number, patch: Partial<UploadState>) =>
        setUploads((all) => all.map((u, j) => (j === i ? { ...u, ...patch } : u)));
      let failed = 0;
      for (const [i, file] of files.entries()) {
        set(i, { status: "uploading" });
        try {
          await uploadOne(workspaceId, projectId, file);
          set(i, { status: "done" });
        } catch (e) {
          failed += 1;
          set(i, { status: "error", error: e instanceof Error ? e.message : "Upload failed" });
        }
      }
      await queryClient.invalidateQueries({ queryKey: ["documents", projectId] });
      return { failed };
    },
    [queryClient],
  );

  return { uploads, upload, reset: () => setUploads([]) };
}

/** Convert a failed document again from its stored original (owners and admins). */
export function useRetryConversion(scope: { workspaceId: string; projectId: string } | null | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/documents/{document_id}/retry", {
          params: { path: { workspace_id: scope!.workspaceId, project_id: scope!.projectId, document_id: documentId } },
        }),
      ),
    onSuccess: (doc) => {
      if (doc.status === "failed") toast.error(`Still couldn't convert it: ${doc.error}`);
    },
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["documents", scope?.projectId] }),
  });
}
