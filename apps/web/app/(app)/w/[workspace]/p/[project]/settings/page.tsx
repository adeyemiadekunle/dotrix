"use client";

import type { Schemas } from "@pmagent/api-client";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Input } from "@pmagent/ui/components/input";
import { Label } from "@pmagent/ui/components/label";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Textarea } from "@pmagent/ui/components/textarea";
import { DownloadIcon, FileTextIcon } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Field, SubmitButton } from "@/components/form";
import { RepoPreview } from "@/components/repo-preview";
import { useUpdateProject } from "@/lib/admin";
import { exportUrl, useManifest } from "@/lib/knowledge";
import { PROJECT_SOURCE_LABELS, canManageProjects } from "@/lib/labels";
import { useProjectScope } from "@/lib/queries";

type Project = Schemas["ProjectRead"];
type Workspace = Schemas["WorkspaceWithRole"];

// Models the backend can run (provider:model); the provider's API key must be set on the server.
const MODEL_SUGGESTIONS = [
  "google_genai:gemini-3.8-flash",
  "anthropic:claude-opus-5-5",
  "anthropic:claude-sonnet-5",
  "anthropic:claude-haiku-4-5-20251001",
];

function General({ project, workspace, canEdit }: { project: Project; workspace: Workspace; canEdit: boolean }) {
  const update = useUpdateProject(workspace.id, project.id);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const changed = name.trim() !== project.name || description.trim() !== project.description;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          General
          <Badge variant="outline" className="font-mono">
            {project.key}
          </Badge>
        </CardTitle>
        <CardDescription>
          Started from {PROJECT_SOURCE_LABELS[project.source].toLowerCase()} on{" "}
          {new Date(project.created_at).toLocaleDateString()}. The key prefixes issue keys and can&apos;t change.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            update.mutate({ name: name.trim(), description: description.trim() });
          }}
        >
          <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} disabled={!canEdit} />
          <div className="grid gap-2">
            <Label htmlFor="project-description">Description</Label>
            <Textarea
              id="project-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              rows={3}
              disabled={!canEdit}
              placeholder="What the project is for"
            />
          </div>
          {canEdit && (
            <SubmitButton pending={update.isPending} disabled={update.isPending || !changed} className="justify-self-start">
              Save
            </SubmitButton>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

/** The project's repo, which owners and admins can link, change, or unlink. */
function Repository({ project, workspace, canEdit }: { project: Project; workspace: Workspace; canEdit: boolean }) {
  const update = useUpdateProject(workspace.id, project.id);
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState("");
  const save = (repo_url: string | null) => update.mutate({ repo_url }, { onSuccess: () => setEditing(false) });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Repository</CardTitle>
        <CardDescription>
          The code repo this project plans for. Teammates link their own checkouts with{" "}
          <code className="font-mono">pmagent connect</code>.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {editing ? (
          <form
            className="grid gap-2"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              save(url.trim());
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
              <Button type="submit" size="sm" disabled={update.isPending}>
                Link repository
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {project.repo_url?.startsWith("https://") ? (
              <a href={project.repo_url} target="_blank" rel="noreferrer" className="break-all underline underline-offset-4">
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
                  <Button size="sm" variant="ghost" className="h-7" disabled={update.isPending} onClick={() => save(null)}>
                    Unlink
                  </Button>
                )}
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Agents({
  project,
  workspace,
  canEdit,
  knowledgeHref,
}: {
  project: Project;
  workspace: Workspace;
  canEdit: boolean;
  knowledgeHref: string;
}) {
  const update = useUpdateProject(workspace.id, project.id);
  const manifest = useManifest({ workspaceId: workspace.id, projectId: project.id });
  const [model, setModel] = useState(project.model);
  const rules = (manifest.data?.files ?? []).filter((f) => f.path.startsWith("agent-rules/") && !f.deleted);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agents</CardTitle>
        <CardDescription>The model the project&apos;s agents run on, and the rules that shape how they behave.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <form
          className="grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            update.mutate({ model: model.trim() });
          }}
        >
          <Label htmlFor="project-model">Model</Label>
          <div className="flex flex-wrap gap-2">
            <Input
              id="project-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              list="model-suggestions"
              className="h-9 min-w-64 flex-1 font-mono text-sm"
              required
              maxLength={100}
              pattern="[a-z_]+:.+"
              disabled={!canEdit}
            />
            <datalist id="model-suggestions">
              {MODEL_SUGGESTIONS.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            {canEdit && (
              <SubmitButton pending={update.isPending} disabled={update.isPending || model.trim() === project.model} className="h-9">
                Save
              </SubmitButton>
            )}
          </div>
          <p className="text-muted-foreground text-xs">
            <code className="font-mono">provider:model</code>, e.g. google_genai, anthropic, or openai. The provider&apos;s API
            key must be configured on the server. New runs use it; running ones finish on the old model.
          </p>
        </form>

        <div className="grid gap-2">
          <h3 className="text-sm font-medium">Agent rules</h3>
          <p className="text-muted-foreground text-xs">
            Every agent reads <code className="font-mono">base.md</code> plus its role file. They live in the project&apos;s
            knowledge, with full history{canEdit ? "" : "; owners and admins edit them"}.
          </p>
          {manifest.isLoading ? (
            <Skeleton className="h-20" />
          ) : (
            <ul className="grid gap-1 sm:grid-cols-2">
              {rules.map((f) => (
                <li key={f.path}>
                  <Link
                    href={`${knowledgeHref}?file=${f.path}`}
                    className="hover:bg-muted flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
                  >
                    <FileTextIcon className="text-muted-foreground size-4" />
                    <span className="truncate">{f.path.replace("agent-rules/", "")}</span>
                    <span className="text-muted-foreground ml-auto text-xs">v{f.version}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/** Project settings: everyone sees them; owners and admins change them. */
export default function ProjectSettings() {
  const { workspace, project, scope, isLoading } = useProjectScope();
  if (isLoading || !project || !workspace || !scope) {
    return (
      <div className="p-4 md:p-6">
        <Skeleton className="h-64 max-w-3xl" />
      </div>
    );
  }
  const canEdit = canManageProjects(workspace.role);
  const base = `/w/${workspace.slug}/p/${project.key}`;
  return (
    <div className="grid max-w-3xl content-start gap-4 p-4 md:p-6">
      <General key={`g-${project.updated_at}`} project={project} workspace={workspace} canEdit={canEdit} />
      <Repository project={project} workspace={workspace} canEdit={canEdit} />
      <Agents key={`a-${project.model}`} project={project} workspace={workspace} canEdit={canEdit} knowledgeHref={`${base}/knowledge`} />
      {canEdit && (
        <Card>
          <CardHeader>
            <CardTitle>Export</CardTitle>
            <CardDescription>
              The whole <code className="font-mono">.pmagent/</code> as Markdown in a zip, with a config.yaml. Leaving the
              platform loses nothing. Knowledge revision {project.knowledge_revision}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" asChild>
              <a href={exportUrl(scope)} download>
                <DownloadIcon />
                Download export
              </a>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
