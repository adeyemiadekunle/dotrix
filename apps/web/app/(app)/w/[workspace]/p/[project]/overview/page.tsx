"use client";

import type { Schemas } from "@pmagent/api-client";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Card, CardContent, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Input } from "@pmagent/ui/components/input";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { RepoPreview } from "@/components/repo-preview";
import { api, errorMessage, unwrap } from "@/lib/api";
import { PROJECT_SOURCE_LABELS, canManageProjects } from "@/lib/labels";
import { useCurrentProject } from "@/lib/queries";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-4 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

/** The project's repo, which owners and admins can link, change, or unlink. */
function Repository({
  project,
  workspace,
}: {
  project: Schemas["ProjectRead"];
  workspace: Schemas["WorkspaceWithRole"];
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState("");
  const save = useMutation({
    mutationFn: (repo_url: string | null) =>
      unwrap(
        api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}", {
          params: { path: { workspace_id: workspace.id, project_id: project.id } },
          body: { repo_url },
        }),
      ),
    onSuccess: async (updated) => {
      toast.success(updated.repo_url ? "Repository linked" : "Repository unlinked");
      setEditing(false);
      await queryClient.invalidateQueries({ queryKey: ["projects", workspace.id] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const canEdit = canManageProjects(workspace.role);

  if (editing) {
    return (
      <form
        className="grid gap-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          save.mutate(url.trim());
        }}
      >
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://github.com/acme/app"
          aria-label="Repository address"
          required
          autoFocus
        />
        <RepoPreview url={url} />
        <div className="flex gap-2">
          <Button type="submit" size="sm" disabled={save.isPending}>
            Link repository
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      </form>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      {project.repo_url?.startsWith("https://") ? (
        <a href={project.repo_url} target="_blank" rel="noreferrer" className="underline underline-offset-4">
          {project.repo_url}
        </a>
      ) : (
        <span className="text-muted-foreground">{project.repo_url ?? "Not linked"}</span>
      )}
      {canEdit && (
        <>
          <Button
            size="sm"
            variant="outline"
            className="h-7"
            onClick={() => {
              setUrl(project.repo_url ?? "");
              setEditing(true);
            }}
          >
            {project.repo_url ? "Change" : "Link repository"}
          </Button>
          {project.repo_url && (
            <Button size="sm" variant="ghost" className="h-7" disabled={save.isPending} onClick={() => save.mutate(null)}>
              Unlink
            </Button>
          )}
        </>
      )}
    </div>
  );
}

export default function ProjectOverview() {
  const { workspace, project, isLoading } = useCurrentProject();

  return (
    <>
      <div className="flex flex-1 flex-col gap-4 p-4 md:p-6">
        {isLoading || !project || !workspace ? (
          <Skeleton className="h-64 max-w-2xl" />
        ) : (
          <Card className="max-w-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Badge variant="outline" className="font-mono">
                  {project.key}
                </Badge>
                {project.name}
              </CardTitle>
              {project.description && <p className="text-muted-foreground text-sm">{project.description}</p>}
            </CardHeader>
            <CardContent>
              <dl className="divide-y">
                <Row label="Started from">{PROJECT_SOURCE_LABELS[project.source]}</Row>
                <Row label="Repository">
                  <Repository project={project} workspace={workspace} />
                </Row>
                <Row label="Agent model">
                  <code className="font-mono text-xs">{project.model}</code>
                </Row>
                <Row label="Knowledge">Revision {project.knowledge_revision}</Row>
                <Row label="Created">{new Date(project.created_at).toLocaleDateString()}</Row>
              </dl>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
