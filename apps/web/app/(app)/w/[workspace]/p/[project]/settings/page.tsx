"use client";

import type { Schemas } from "@pmagent/api-client";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Input } from "@pmagent/ui/components/input";
import { Label } from "@pmagent/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Textarea } from "@pmagent/ui/components/textarea";
import { ArrowRightLeftIcon, BotIcon, DownloadIcon, FileTextIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useConfirm } from "@/components/confirm-dialog";
import { Field, SaveBar } from "@/components/form";
import { RepoPreview } from "@/components/repo-preview";
import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { useMoveProject, useUpdateProject } from "@/lib/admin";
import { exportUrl, useManifest } from "@/lib/knowledge";
import { PROJECT_SOURCE_LABELS, WORKSPACE_KIND_LABELS, can, canManageProjects } from "@/lib/labels";
import { useProjectScope, useWorkspaces } from "@/lib/queries";

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
    <SettingsSection id="general">
      <SettingsHeader>
        <SettingsTitle className="flex items-center gap-2">
          General
          <Badge variant="outline" className="font-mono">
            {project.key}
          </Badge>
        </SettingsTitle>
        <SettingsDescription>
          Started from {PROJECT_SOURCE_LABELS[project.source].toLowerCase()} on{" "}
          {new Date(project.created_at).toLocaleDateString()}. The key prefixes issue keys and can&apos;t change.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent>
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
            <SaveBar
              dirty={changed}
              pending={update.isPending}
              onDiscard={() => {
                setName(project.name);
                setDescription(project.description);
              }}
            />
          )}
        </form>
      </SettingsContent>
    </SettingsSection>
  );
}

/** The project's repo, which owners and admins can link, change, or unlink. */
function Repository({ project, workspace, canEdit }: { project: Project; workspace: Workspace; canEdit: boolean }) {
  const update = useUpdateProject(workspace.id, project.id);
  const [editing, setEditing] = useState(false);
  const [url, setUrl] = useState("");
  const save = (repo_url: string | null) => update.mutate({ repo_url }, { onSuccess: () => setEditing(false) });

  return (
    <SettingsSection id="repository">
      <SettingsHeader>
        <SettingsTitle>Repository</SettingsTitle>
        <SettingsDescription>
          The code repo this project plans for. Teammates link their own checkouts with{" "}
          <code className="font-mono">pmagent connect</code>.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent>
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
      </SettingsContent>
    </SettingsSection>
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
  const [specialistModel, setSpecialistModel] = useState(project.specialist_model ?? "");
  const [budget, setBudget] = useState(project.token_budget ? String(project.token_budget) : "");
  const specialistChanged = specialistModel.trim() !== (project.specialist_model ?? "");
  const budgetChanged = budget.trim() !== (project.token_budget ? String(project.token_budget) : "");
  const rules = (manifest.data?.files ?? []).filter((f) => f.path.startsWith("agent-rules/") && !f.deleted);
  return (
    <SettingsSection id="agents">
      <SettingsHeader>
        <SettingsTitle>Agents</SettingsTitle>
        <SettingsDescription>
          The models the project&apos;s agents run on, how much one request may use, and the rules that shape how they behave.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="grid gap-6">
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
          </div>
          <p className="text-muted-foreground text-xs">
            <code className="font-mono">provider:model</code>, e.g. google_genai, anthropic, or openai. The provider&apos;s API
            key must be configured on the server. New runs use it; running ones finish on the old model.
          </p>
          {canEdit && (
            <SaveBar dirty={model.trim() !== project.model} pending={update.isPending} onDiscard={() => setModel(project.model)} />
          )}
        </form>

        <form
          className="grid gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            update.mutate({
              ...(specialistChanged ? { specialist_model: specialistModel.trim() || null } : {}),
              ...(budgetChanged ? { token_budget: budget.trim() ? Number(budget) : null } : {}),
            });
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="project-specialist-model">Model for specialists and summaries</Label>
            <Input
              id="project-specialist-model"
              value={specialistModel}
              onChange={(e) => setSpecialistModel(e.target.value)}
              list="model-suggestions"
              placeholder={`Same as the project (${project.model})`}
              className="h-9 min-w-64 font-mono text-sm"
              maxLength={100}
              pattern="[a-z_]+:.+"
              disabled={!canEdit}
            />
            <p className="text-muted-foreground text-xs">
              A cheaper model for the product, architecture, research, reviewer, and documentation agents, and for
              summarising long conversations. The project manager (Auto) and any agent you pick in Chat use the
              conversation&apos;s model. Leave it empty to use the same model.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="project-token-budget">Token budget per request</Label>
            <Input
              id="project-token-budget"
              type="number"
              inputMode="numeric"
              min={10000}
              max={10000000}
              step={1000}
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              placeholder="The server's default"
              className="h-9 w-48 text-sm"
              disabled={!canEdit}
            />
            <p className="text-muted-foreground text-xs">
              The most tokens one request to the agents may use, including every specialist it asks and every step after
              an approval. A request that reaches it stops and says so. Leave it empty for the server&apos;s default.
            </p>
          </div>
          {canEdit && (
            <SaveBar
              dirty={specialistChanged || budgetChanged}
              pending={update.isPending}
              onDiscard={() => {
                setSpecialistModel(project.specialist_model ?? "");
                setBudget(project.token_budget ? String(project.token_budget) : "");
              }}
            />
          )}
        </form>

        <div className="grid gap-2">
          <h3 className="text-sm font-medium">Who the agents are</h3>
          <p className="text-muted-foreground text-xs">
            Their instructions, tools, folder access, and what they may do without asking come from the workspace&apos;s
            agents; this project can have its own versions and agents of its own.
          </p>
          <div>
            <Button variant="outline" size="sm" asChild>
              <Link href={`${knowledgeHref.replace(/\/knowledge$/, "")}/settings/agents`}>
                <BotIcon />
                Agents for this project
              </Link>
            </Button>
          </div>
        </div>

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
      </SettingsContent>
    </SettingsSection>
  );
}

/** Move the project to another workspace where you can set up projects: from your personal
 * workspace into an organisation's, or back. */
function Move({ project, workspace }: { project: Project; workspace: Workspace }) {
  const workspaces = useWorkspaces();
  const move = useMoveProject(workspace.id, project.id);
  const router = useRouter();
  const [ask, confirmDialog] = useConfirm();
  const [choice, setChoice] = useState("");
  const targets = (workspaces.data ?? []).filter((w) => w.id !== workspace.id && can(w, "projects:manage"));
  const target = targets.find((w) => w.id === choice);
  return (
    <SettingsSection id="move">
      <SettingsHeader>
        <SettingsTitle>Move project</SettingsTitle>
        <SettingsDescription>
          Move {project.name} to another workspace, for example from your personal workspace into an organisation&apos;s
          so you can work on it with others. Its documents, issues, uploads, and conversations go with it; the people who
          see it are the other workspace&apos;s.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="grid gap-3">
        {targets.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            There&apos;s no other workspace where you can add projects.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Select value={choice} onValueChange={setChoice}>
              <SelectTrigger className="min-w-64" aria-label="Workspace to move to">
                <SelectValue placeholder="Choose a workspace" />
              </SelectTrigger>
              <SelectContent>
                {targets.map((w) => (
                  <SelectItem key={w.id} value={w.id}>
                    {w.name} · {WORKSPACE_KIND_LABELS[w.kind]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              disabled={!target || move.isPending}
              onClick={() =>
                target &&
                ask({
                  title: `Move ${project.key} to ${target.name}?`,
                  description:
                    "Everyone in that workspace will see it, and people who are only in this one won't: they're unassigned from its issues and stop watching them. Linked checkouts follow it on their next command.",
                  confirm: "Move project",
                  action: async () => {
                    await move.mutateAsync(target.id);
                    router.push(`/w/${target.slug}/p/${project.key}/settings`);
                  },
                })
              }
            >
              <ArrowRightLeftIcon />
              Move
            </Button>
          </div>
        )}
        <p className="text-muted-foreground text-xs">
          You need to be an owner or admin in both workspaces. It can&apos;t move while an agent is working or waiting for
          approval, or if the other workspace already has a project with key {project.key} or the same repository.
        </p>
        {confirmDialog}
      </SettingsContent>
    </SettingsSection>
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
  const sections = [
    ["general", "General"],
    ["repository", "Repository"],
    ["agents", "Agents"],
    ...(canEdit ? [["export", "Export"], ["move", "Move project"]] : []),
  ];
  return (
    <div className="flex items-start gap-10 p-4 md:p-8">
      <div className="grid max-w-5xl min-w-0 flex-1 content-start gap-8">
        <General key={`g-${project.updated_at}`} project={project} workspace={workspace} canEdit={canEdit} />
        <Repository project={project} workspace={workspace} canEdit={canEdit} />
        <Agents
          key={`a-${project.model}-${project.specialist_model}-${project.token_budget}`}
          project={project}
          workspace={workspace}
          canEdit={canEdit}
          knowledgeHref={`${base}/knowledge`}
        />
        {canEdit && (
          <SettingsSection id="export">
            <SettingsHeader>
              <SettingsTitle>Export</SettingsTitle>
              <SettingsDescription>
                The whole <code className="font-mono">.pmagent/</code> as Markdown in a zip, with a config.yaml. Leaving the
                platform loses nothing. Knowledge revision {project.knowledge_revision}.
              </SettingsDescription>
            </SettingsHeader>
            <SettingsContent>
              <Button variant="outline" asChild>
                <a href={exportUrl(scope)} download>
                  <DownloadIcon />
                  Download export
                </a>
              </Button>
            </SettingsContent>
          </SettingsSection>
        )}
        {canEdit && <Move project={project} workspace={workspace} />}
      </div>
      <nav aria-label="On this page" className="sticky top-20 hidden w-40 shrink-0 text-sm xl:grid">
        <p className="text-muted-foreground pb-2 text-xs font-medium">On this page</p>
        {sections.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="text-muted-foreground hover:text-foreground rounded-md py-1">
            {label}
          </a>
        ))}
      </nav>
    </div>
  );
}
