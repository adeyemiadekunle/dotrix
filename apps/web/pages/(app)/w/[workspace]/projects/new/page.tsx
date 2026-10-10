import type { Schemas } from "@dotrix/api-client";
import { Button } from "@dotrix/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@dotrix/ui/components/card";
import { Checkbox } from "@dotrix/ui/components/checkbox";
import { Label } from "@dotrix/ui/components/label";
import { RadioGroup, RadioGroupItem } from "@dotrix/ui/components/radio-group";
import { Textarea } from "@dotrix/ui/components/textarea";
import { cn } from "@dotrix/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import {
  CircleAlertIcon,
  FilesIcon,
  FolderGit2Icon,
  GitBranchPlusIcon,
  type LucideIcon,
} from "lucide-react";
import { Link, useRouter } from "@/lib/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app-shell";
import { Dropzone, QueuedFiles, UploadProgress } from "@/components/documents/dropzone";
import { RepoPicker } from "@/components/github-repos";
import { RepoPreview } from "@/components/repo-preview";
import { Field, FormError, SubmitButton } from "@/components/form";
import { NotFound } from "@/components/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useUploads } from "@/lib/documents";
import { type RepoOption, useGitHubStatus } from "@/lib/github";
import { canManageProjects, suggestKey } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";
import { usePublicGithubRepo } from "@/lib/repo";

type Source = "existing_repo" | "docs_only" | "new_repo";

const SOURCES: { value: Source; label: string; description: string; icon: LucideIcon }[] = [
  {
    value: "existing_repo",
    label: "Existing repository",
    description: "Connect the project's code repo, so agents understand the codebase.",
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
    description: "Create the repo on GitHub, in an organisation the GitHub App is installed on.",
    icon: GitBranchPlusIcon,
  },
];

export default function NewProjectPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { workspace, notFound } = useCurrentWorkspace();
  const { uploads, upload } = useUploads();

  const [source, setSource] = useState<Source>("existing_repo");
  const [repoUrl, setRepoUrl] = useState("");
  // Picked from the GitHub App's repos: connected as soon as the project exists.
  const [picked, setPicked] = useState<RepoOption | null>(null);
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [phase, setPhase] = useState<"form" | "creating" | "uploading" | "done">("form");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Schemas["ProjectRead"] | null>(null);
  const publicRepo = usePublicGithubRepo(source === "existing_repo" && !picked ? repoUrl : "");
  const github = useGitHubStatus(workspace?.id, !!workspace && canManageProjects(workspace.role));
  // A new repo: in which organisation (its installation here), called what, and private or not.
  const orgs = (github.data?.installations ?? []).filter((i) => i.account_type === "Organization" && !i.suspended);
  const [orgRef, setOrgRef] = useState("");
  const [repoName, setRepoName] = useState("");
  const [repoNameEdited, setRepoNameEdited] = useState(false);
  const [repoPrivate, setRepoPrivate] = useState(true);
  const org = orgs.find((i) => i.id === orgRef) ?? orgs[0];

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
          <code className="font-mono">dotrix connect</code> in its repo.
        </p>
      </>
    );
  }

  function setNameAndKey(next: string) {
    setName(next);
    if (!keyEdited) setKey(suggestKey(next));
    if (!repoNameEdited) setRepoName(slugify(next));
  }

  function pick(repo: RepoOption) {
    setPicked(repo);
    setRepoUrl(repo.html_url);
    const repoName = repo.full_name.split("/")[1] ?? "";
    if (!name) setNameAndKey(repoName);
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
      if (!created && source === "new_repo" && org) {
        // The project exists first: if GitHub refuses the repo, it can connect one later.
        try {
          const repo = await unwrap(
            api.POST("/v1/workspaces/{workspace_id}/github/repos", {
              params: { path: { workspace_id: workspace.id } },
              body: { installation_ref: org.id, name: repoName, private: repoPrivate, description },
            }),
          );
          await unwrap(
            api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", {
              params: { path: { workspace_id: workspace.id, project_id: project.id } },
              body: { installation_ref: repo.installation_ref, github_repo_id: repo.github_repo_id },
            }),
          );
          toast.success(`Created ${repo.full_name} on GitHub`);
        } catch (e) {
          toast.error(`The project was created, but its repository wasn't: ${errorMessage(e)}. Connect one in its settings.`);
        }
      }
      if (!created && source === "existing_repo" && picked) {
        // The address is the repo's already, so this only adds the app's access to it.
        await unwrap(
          api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", {
            params: { path: { workspace_id: workspace.id, project_id: project.id } },
            body: { installation_ref: picked.installation_ref, github_repo_id: picked.github_repo_id },
          }),
        ).catch((e: unknown) => toast.error(`The project was created, but connecting the repo didn't work: ${errorMessage(e)}`));
      }
      await queryClient.invalidateQueries({ queryKey: ["projects", workspace.id] });
      if (files.length === 0) {
        router.push(`/w/${workspace.slug}/p/${project.key}`);
        return;
      }
      setPhase("uploading");
      const { failed } = await upload(workspace.id, project.id, files);
      if (failed === 0) {
        router.push(`/w/${workspace.slug}/p/${project.key}/files`);
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
              {SOURCES.map(({ value, label, description: text, icon: Icon }) => (
                <Label
                  key={value}
                  className="has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:ring-primary/20 flex cursor-pointer flex-col items-start gap-2 rounded-lg border p-3 font-normal has-[[data-state=checked]]:ring-2"
                >
                  <RadioGroupItem value={value} className="sr-only" />
                  <span className="flex w-full items-center gap-2 font-medium">
                    <Icon className="size-4" />
                    {label}
                  </span>
                  <span className="text-muted-foreground text-xs leading-snug">{text}</span>
                </Label>
              ))}
            </RadioGroup>

            {source === "new_repo" && workspace && (
              <NewRepoFields
                workspaceId={workspace.id}
                settingsHref={`/w/${workspace.slug}/settings/github`}
                configured={!!github.data?.configured}
                loading={!github.data}
                orgs={orgs}
                org={org}
                onOrg={setOrgRef}
                name={repoName}
                onName={(next) => {
                  setRepoName(next);
                  setRepoNameEdited(true);
                }}
                isPrivate={repoPrivate}
                onPrivate={setRepoPrivate}
                disabled={busy || Boolean(created)}
              />
            )}

            {source === "existing_repo" && (
              <div className="grid gap-4">
                {github.data?.configured && workspace && (
                  <div className="grid gap-2">
                    <Label>From GitHub</Label>
                    {created ? (
                      <p className="text-sm">{picked?.full_name ?? repoUrl}</p>
                    ) : (
                      <RepoPicker
                        workspaceId={workspace.id}
                        value={picked}
                        onPick={pick}
                        settingsHref={`/w/${workspace.slug}/settings/github`}
                      />
                    )}
                  </div>
                )}
                <div className="grid gap-2">
                  <Field
                    label={github.data?.configured ? "Or paste its address" : "Repository"}
                    value={repoUrl}
                    onChange={(e) => {
                      setRepoUrl(e.target.value);
                      setPicked(null);
                    }}
                    placeholder="https://github.com/acme/app"
                    required
                    disabled={busy || Boolean(created)}
                    hint="Any host works by address; teammates link their own checkouts with dotrix connect. One project per repo in a workspace."
                  />
                  {!picked && <RepoPreview url={repoUrl} />}
                </div>
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
              <Link href={`${projectHref}/files`}>Open project</Link>
            </Button>
          ) : (
            <>
              <Button type="button" variant="outline" asChild disabled={busy}>
                <Link href={workspace ? `/w/${workspace.slug}` : "/"}>Cancel</Link>
              </Button>
              <SubmitButton pending={busy} disabled={busy || (source === "new_repo" && !org)}>
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


/** A repo name from a project name: "Kunemi web app" → "kunemi-web-app". */
function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

type Installation = Schemas["InstallationRead"];

/** Where the new repo goes and what it's called; or what to do first when that isn't possible. */
function NewRepoFields(props: {
  workspaceId: string;
  settingsHref: string;
  configured: boolean;
  loading: boolean;
  orgs: Installation[];
  org: Installation | undefined;
  onOrg: (ref: string) => void;
  name: string;
  onName: (name: string) => void;
  isPrivate: boolean;
  onPrivate: (value: boolean) => void;
  disabled: boolean;
}) {
  const { orgs, org } = props;
  if (props.loading) return null;
  if (!props.configured || orgs.length === 0) {
    return (
      <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-sm" role="note">
        {props.configured
          ? "GitHub lets the app create repositories only in organisations. "
          : "Creating repositories needs the GitHub App, which isn't set up on this server yet. "}
        {props.configured && (
          <>
            Install it on an organisation in{" "}
            <Link href={props.settingsHref} className="underline underline-offset-4">
              Settings → GitHub
            </Link>
            , or create the repo on GitHub and pick it under Existing repository.
          </>
        )}
      </p>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-[auto_1fr]">
      <div className="grid gap-2">
        <Label htmlFor="repo-org">Organisation</Label>
        <select
          id="repo-org"
          value={org?.id}
          onChange={(e) => props.onOrg(e.target.value)}
          disabled={props.disabled}
          className="bg-background h-9 rounded-md border px-2 text-sm"
        >
          {orgs.map((i) => (
            <option key={i.id} value={i.id}>
              {i.account_login}
            </option>
          ))}
        </select>
      </div>
      <Field
        label="Repository name"
        value={props.name}
        onChange={(e) => props.onName(e.target.value)}
        placeholder="kunemi-app"
        required
        pattern="[A-Za-z0-9._-]+"
        maxLength={100}
        disabled={props.disabled}
        hint={org ? `github.com/${org.account_login}/${props.name || "…"} · created with a README` : undefined}
      />
      <Label className="flex items-center gap-2 font-normal sm:col-span-2">
        <Checkbox
          checked={props.isPrivate}
          onCheckedChange={(checked) => props.onPrivate(checked === true)}
          disabled={props.disabled}
        />
        Private repository
      </Label>
    </div>
  );
}
