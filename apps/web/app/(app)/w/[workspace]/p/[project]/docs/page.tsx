"use client";

import type { Schemas } from "@pmagent/api-client";
import { Button } from "@pmagent/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@pmagent/ui/components/sheet";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useQuery } from "@tanstack/react-query";
import { DownloadIcon, EyeIcon, FileTextIcon, FilesIcon, LayersIcon, Loader2Icon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useChat } from "@/components/agent/chat-context";
import { Dropzone, UploadProgress } from "@/components/documents/dropzone";
import { timeAgo } from "@/components/issues/issue-activity";
import { Markdown } from "@/components/markdown";
import { EmptyState } from "@/components/states";
import { useArchitectureDraft } from "@/lib/agent";
import { ApiError } from "@/lib/api";
import { formatBytes, originalUrl, useDocuments, useUploads, type Document } from "@/lib/documents";
import { useMembers } from "@/lib/issues";
import { canManageProjects } from "@/lib/labels";
import { useProjectScope } from "@/lib/queries";

/** The Markdown the agents read for a document (its knowledge file). */
function ConvertedView({
  scope,
  document,
  onClose,
  knowledgeHref,
}: {
  scope: { workspaceId: string; projectId: string };
  document: Document | null;
  onClose: () => void;
  knowledgeHref?: string;
}) {
  const file = useQuery({
    queryKey: ["knowledge-file", scope.projectId, document?.knowledge_path],
    queryFn: async () => {
      const response = await fetch(
        `/api/v1/workspaces/${scope.workspaceId}/projects/${scope.projectId}/knowledge/files/${document!.knowledge_path}`,
      );
      if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => undefined));
      return (await response.json()) as Schemas["FileRead"];
    },
    enabled: Boolean(document),
  });
  return (
    <Sheet open={Boolean(document)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{document?.filename}</SheetTitle>
          <SheetDescription>
            What the agents read: <code className="font-mono">{document?.knowledge_path}</code>
            {file.data && ` · version ${file.data.version}`}
            {knowledgeHref && document && (
              <>
                {" · "}
                <Link href={`${knowledgeHref}?file=${document.knowledge_path}`} className="underline underline-offset-4">
                  Open in Knowledge
                </Link>
              </>
            )}
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-8">
          {file.isLoading && <Skeleton className="h-64" />}
          {file.isError && <p className="text-muted-foreground text-sm">Couldn&apos;t load the converted text.</p>}
          {file.data && <Markdown>{file.data.content ?? ""}</Markdown>}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default function DocsPage() {
  const { workspace, project, scope } = useProjectScope();
  const documents = useDocuments(scope);
  const members = useMembers(workspace?.id);
  const { uploads, upload, reset } = useUploads();
  const [viewing, setViewing] = useState<Document | null>(null);
  const [uploading, setUploading] = useState(false);
  const names = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m.display_name])), [members.data]);
  const canUpload = canManageProjects(workspace?.role);
  const draft = useArchitectureDraft(scope);
  const chat = useChat();

  async function onFiles(files: File[]) {
    if (!scope) return;
    reset();
    setUploading(true);
    await upload(scope.workspaceId, scope.projectId, files);
    setUploading(false);
  }

  return (
    <div className="grid max-w-4xl content-start gap-4 p-4 md:p-6">
      {canUpload && (
        <Card>
          <CardHeader>
            <CardTitle>Add documents</CardTitle>
            <CardDescription>
              Each is converted to Markdown under <code className="font-mono">docs/normalized/</code>, where the agents
              read it. Uploading a file with the same name again adds a new version.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <Dropzone onFiles={(f) => void onFiles(f)} disabled={uploading} />
            <UploadProgress uploads={uploads} />
          </CardContent>
        </Card>
      )}

      {canUpload && (documents.data?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Architecture overview</CardTitle>
            <CardDescription>
              Have the Architecture agent draft <code className="font-mono">architecture/overview.md</code> from these
              documents (and the linked repo&apos;s README). It&apos;s setup work: you review the draft and approve it in
              the chat before anything is written.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="outline"
              disabled={draft.isPending}
              onClick={async () => {
                const run = await draft.mutateAsync().catch(() => null);
                if (run) chat.show(run.thread_id);
              }}
            >
              {draft.isPending ? <Loader2Icon className="animate-spin" /> : <LayersIcon />}
              Draft architecture overview
            </Button>
          </CardContent>
        </Card>
      )}

      <section className="grid gap-3">
        <h2 className="font-medium">Documents</h2>
        {documents.isLoading && <Skeleton className="h-40" />}
        {documents.data?.length === 0 && (
          <EmptyState
            icon={FilesIcon}
            title="No documents yet"
            description={
              canUpload
                ? "Add the project's specs, PRDs, and research so the agents work from them."
                : "An owner or admin adds the project's documents."
            }
          />
        )}
        {documents.data && documents.data.length > 0 && (
          <ul className="divide-y rounded-lg border">
            {documents.data.map((doc) => (
              <li key={doc.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                <FileTextIcon className="text-muted-foreground size-4 shrink-0" />
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="truncate font-medium">{doc.filename}</span>
                  <span className="text-muted-foreground text-xs">
                    {formatBytes(doc.size)} · added {timeAgo(doc.created_at)}
                    {doc.uploaded_by_id && ` by ${names.get(doc.uploaded_by_id) ?? "a former member"}`}
                    {doc.knowledge_version > 1 && ` · version ${doc.knowledge_version}`}
                  </span>
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="outline" onClick={() => setViewing(doc)}>
                    <EyeIcon />
                    View text
                  </Button>
                  {scope && (
                    <Button size="sm" variant="ghost" asChild>
                      <a href={originalUrl(scope.workspaceId, scope.projectId, doc.id)} download={doc.filename}>
                        <DownloadIcon />
                        <span className="sr-only sm:not-sr-only">Original</span>
                      </a>
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      {scope && <ConvertedView
          scope={scope}
          document={viewing}
          onClose={() => setViewing(null)}
          knowledgeHref={workspace && project ? `/w/${workspace.slug}/p/${project.key}/knowledge` : undefined}
        />}
    </div>
  );
}
