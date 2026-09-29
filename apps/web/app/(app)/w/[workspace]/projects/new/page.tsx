"use client";

import type { Schemas } from "@pmagent/api-client";
import { Button } from "@pmagent/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Label } from "@pmagent/ui/components/label";
import { RadioGroup, RadioGroupItem } from "@pmagent/ui/components/radio-group";
import { Textarea } from "@pmagent/ui/components/textarea";
import { cn } from "@pmagent/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import {
  CircleAlertIcon,
  FilesIcon,
  FolderGit2Icon,
  GitBranchPlusIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app-shell";
import { Dropzone, QueuedFiles, UploadProgress } from "@/components/documents/dropzone";
import { RepoPreview } from "@/components/repo-preview";
import { Field, FormError, SubmitButton } from "@/components/form";
import { NotFound } from "@/components/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useUploads } from "@/lib/documents";
import { canManageProjects, suggestKey } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";
import { usePublicGithubRepo } from "@/lib/repo";

type Source = "existing_repo" | "docs_only";

const SOURCES: { value: Source | "new_repo"; label: string; description: string; icon: LucideIcon; soon?: boolean }[] = [
  {
    value: "existing_repo",
    label: "Existing repository",
    description: "Link the project's code repo. Its README and layout inform the architecture overview.",
    icon: FolderGit2Icon,
  },
  {
    value: "docs_only",
    label: "Documents only",
    description: "Start from specs, PRDs, and notes; connect a repo later.",
    icon: FilesIcon,
  },
  {
    value: "new_repo",
    label: "New repository",
    description: "Create the repo on GitHub for you. Needs the GitHub connection.",
    icon: GitBranchPlusIcon,
    soon: true,
  },
];

export default function NewProjectPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { workspace, notFound } = useCurrentWorkspace();
  const { uploads, upload } = useUploads();

  const [source, setSource] = useState<Source>("existing_repo");
  const [repoUrl, setRepoUrl] = useState("");
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [phase, setPhase] = useState<"form" | "creating" | "uploading" | "done">("form");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Schemas["ProjectRead"] | null>(null);
  const publicRepo = usePublicGithubRepo(source === "existing_repo" ? repoUrl : "");

  // Prefill the name and description from a public repo, once per repo, only into empty fields.
  const prefilled = useRef<string | null>(null);
  const found = publicRepo.data;
  useEffect(() => {
    if (!found || prefilled.current === found.fullName) return;
    prefilled.current = found.fullName;
    const repoName = found.fullName.split("/")[1] ?? "";
    setName((current) => {
      if (current) return current;
      if (!keyEdited) setKey(suggestKey(repoName));
      return repoName;
    });
    setDescription((current) => current || found.description.slice(0, 500));
  }, [found, keyEdited]);

  if (notFound) return <NotFound what="workspace" />;
  if (workspace && !canManageProjects(workspace.role)) {
    return (
      <>
        <PageHeader title="New project" parent={workspace.name} />
        <p className="text-muted-foreground p-6 text-sm">
          Only owners and admins set up projects. To work on an existing project from your machine, run{" "}
          <code className="font-mono">pmagent connect</code> in its repo.
        </p>
      </>
    );
  }

  function setNameAndKey(next: string) {
    setName(next);
    if (!keyEdited) setKey(suggestKey(next));
  }


  const busy = phase === "creating" || phase === "uploading";
  const projectHref = created && workspace ? `/w/${workspace.slug}/p/${created.key}` : "";

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!workspace) return;
    setError(null);
    setPhase("creating");
    try {
      const project =
        created ??
        (await unwrap(
          api.POST("/v1/workspaces/{workspace_id}/projects", {
            params: { path: { workspace_id: workspace.id } },
            body: {
              name,
              key,
              description,
              source,
              repo_url: source === "existing_repo" ? repoUrl.trim() : null,
              access: "workspace",
            },
          }),
        ));
      setCreated(project);
      await queryClient.invalidateQueries({ queryKey: ["projects", workspace.id] });
      if (files.length === 0) {
        router.push(`/w/${workspace.slug}/p/${project.key}`);
        return;
      }
      setPhase("uploading");
      const { failed } = await upload(workspace.id, project.id, files);
      if (failed === 0) {
        router.push(`/w/${workspace.slug}/p/${project.key}/docs`);
        return;
      }
      setPhase("done");
    } catch (e) {
      setError(errorMessage(e));
      setPhase("form");
    }
  }

  return (
    <>
      <PageHeader title="New project" parent={workspace?.name} />
      <form onSubmit={onSubmit} className="grid max-w-2xl gap-4 p-4 md:p-6">
        <FormError message={error} />

        <Card>
          <CardHeader>
            <CardTitle>Where does it start?</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <RadioGroup
              value={source}
              onValueChange={(v) => setSource(v as Source)}
              className="grid gap-2 sm:grid-cols-3"
              disabled={busy || Boolean(created)}
            >
              {SOURCES.map(({ value, label, description: text, icon: Icon, soon }) => (
                <Label
                  key={value}
                  className={cn(
                    "has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:ring-primary/20 flex cursor-pointer flex-col items-start gap-2 rounded-lg border p-3 font-normal has-[[data-state=checked]]:ring-2",
                    soon && "cursor-not-allowed opacity-60",
                  )}
                >
                  <RadioGroupItem value={value} disabled={soon} className="sr-only" />
                  <span className="flex w-full items-center gap-2 font-medium">
                    <Icon className="size-4" />
                    {label}
                    {soon && <span className="text-muted-foreground ml-auto text-[10px] font-normal">Soon</span>}
                  </span>
                  <span className="text-muted-foreground text-xs leading-snug">{text}</span>
                </Label>
              ))}
            </RadioGroup>

            {source === "existing_repo" && (
              <div className="grid gap-2">
                <Field
                  label="Repository"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  placeholder="https://github.com/acme/app"
                  required
                  disabled={busy || Boolean(created)}
                  hint="Paste the address you'd clone. One project per repo in a workspace; teammates link their own checkouts with pmagent connect."
                />
                <RepoPreview url={repoUrl} />
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <Field
              label="Name"
              value={name}
              onChange={(e) => setNameAndKey(e.target.value)}
              placeholder="Kumove"
              required
              maxLength={100}
              disabled={busy || Boolean(created)}
            />
            <Field
              label="Key"
              value={key}
              onChange={(e) => {
                setKey(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""));
                setKeyEdited(true);
              }}
              placeholder="KUN"
              required
              minLength={2}
              maxLength={10}
              pattern="[A-Z][A-Z0-9]{1,9}"
              className="font-mono uppercase"
              disabled={busy || Boolean(created)}
              hint="Prefixes issue keys, like KUN-42. 2–10 letters or digits, starting with a letter; can't be changed."
            />
            <div className="grid gap-2">
              <Label htmlFor="project-description">Description</Label>
              <Textarea
                id="project-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What the project is for, in a sentence or two"
                maxLength={500}
                rows={2}
                disabled={busy || Boolean(created)}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Project documents</CardTitle>
            <CardDescription>
              The agents read these. Each is converted to Markdown in the project&apos;s knowledge; the original is kept
              too. You can add more later from the Docs tab.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {phase === "form" && !created && (
              <>
                <Dropzone onFiles={(picked) => setFiles((f) => [...f, ...picked])} disabled={busy} />
                <QueuedFiles files={files} onRemove={(i) => setFiles((f) => f.filter((_, j) => j !== i))} />
              </>
            )}
            <UploadProgress uploads={uploads} />
            {phase === "done" && (
              <p className="text-muted-foreground flex items-start gap-1.5 text-sm">
                <CircleAlertIcon className="text-destructive mt-0.5 size-4 shrink-0" />
                The project was created, but some documents didn&apos;t upload. Try them again from the Docs tab.
              </p>
            )}
          </CardContent>
        </Card>

        <div className="flex justify-end gap-2">
          {phase === "done" && created ? (
            <Button asChild>
              <Link href={`${projectHref}/docs`}>Open project</Link>
            </Button>
          ) : (
            <>
              <Button type="button" variant="outline" asChild disabled={busy}>
                <Link href={workspace ? `/w/${workspace.slug}` : "/"}>Cancel</Link>
              </Button>
              <SubmitButton pending={busy}>
                {phase === "creating"
                  ? "Creating project…"
                  : phase === "uploading"
                    ? "Uploading documents…"
                    : files.length
                      ? `Create project and add ${files.length} document${files.length === 1 ? "" : "s"}`
                      : "Create project"}
              </SubmitButton>
            </>
          )}
        </div>
      </form>
    </>
  );
}
