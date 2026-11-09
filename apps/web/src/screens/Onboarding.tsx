// Setting up: one decision per screen, with progress dots and Skip wherever a step is optional.
// Your profile (and, only if you want one, an organisation), how you want to start (an idea, a new
// codebase, or an existing repository), the project, GitHub (not for an idea), your AI provider,
// and what's ready. GitHub and the AI provider can wait: a project is useful without them.
// Only server-confirmed workspace and project IDs are kept in the URL across refreshes, sign-in and
// GitHub's redirect, so setup resumes where it was; keys stay in memory. A save whose response was
// lost is recovered from what the server saved, never made twice.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, hasSession, unwrap, type Schemas } from "@/lib/api";
import { installGitHub, myDefaultModelSaved, myKeySaved, myModels } from "../data/account";
import { AGENTS, CODING_AGENT } from "../data/seed-dotrix";
import { Ic } from "../core/icons";
import { PROJECT_STARTS, projectStart, projectDiscussionHref, projectImplementationHref, readProjectStart, type ProjectStart } from "../core/projectSetup";
import { Face } from "../ui/face";
import { RepositoryCreate } from "./RepositoryCreate";
import { ProjectReadiness } from "../views/ProjectReadiness";

type Step = "workspace" | "start" | "project" | "github" | "model" | "ready";
const steps: Step[] = ["start", "project", "github", "model", "ready"];
const stepNames: Record<Step, string> = {
  workspace: "Profile",
  start: "Starting point",
  project: "Project",
  github: "GitHub",
  model: "AI provider",
  ready: "Ready",
};

export function Onboarding() {
  const queryClient = useQueryClient();
  const query = new URLSearchParams(location.search);
  const addingProject = query.get("mode") === "project";
  const initialWorkspaceFlow = useRef(!addingProject && !query.has("workspace") && !query.has("project")).current;
  const workspaceChoiceState = useRef<"unseen" | "pending" | "reviewed">("unseen");
  const submission = useRef(false);
  const [selectedStart, setStart] = useState<ProjectStart | null>(readProjectStart(query.get("intent")));
  const [workspaceId, setWorkspace] = useState(query.get("workspace") ?? "");
  const [projectId, setProject] = useState(query.get("project") ?? "");
  const [step, setStep] = useState<Step>(
    steps.includes(query.get("step") as Step) || (!addingProject && query.get("step") === "workspace")
      ? (query.get("step") as Step)
      : readProjectStart(query.get("intent"))
        ? "project"
        : "start",
  );
  const [teamName, setTeamName] = useState("");
  const [workspaceKind, setWorkspaceKind] = useState<"personal" | "organization">("personal");
  const [creatingTeam, setCreatingTeam] = useState(query.get("team") === "1");
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [accessLevel, setAccessLevel] = useState<"workspace" | "restricted">("workspace");
  const [key, setKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [repoId, setRepo] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const signedIn = hasSession();
  const profile = useQuery({ queryKey: ["onboarding-profile"], enabled: signedIn, queryFn: () => unwrap(api.GET("/v1/me")) });
  const workspaces = useQuery({ queryKey: ["workspaces"], enabled: signedIn, queryFn: () => unwrap(api.GET("/v1/workspaces")) });
  const workspace = workspaces.data?.find((item) => item.id === workspaceId);
  const knownWorkspaces = workspaces.data;
  const reloadWorkspaceChoices = workspaces.refetch;
  const observedSavedChoice = initialWorkspaceFlow && workspaceChoiceState.current === "pending" ? profile.data?.onboarding_workspace_id : null;
  const savedChoiceIsKnown = !!observedSavedChoice && !!knownWorkspaces?.some((item) => item.id === observedSavedChoice);
  const summaryWorkspace = observedSavedChoice ? workspaces.data?.find((item) => item.id === observedSavedChoice) : workspace;
  useEffect(() => {
    if (!workspaces.data || !profile.data) return;
    if (workspaceChoiceState.current === "unseen")
      workspaceChoiceState.current = initialWorkspaceFlow && !profile.data.onboarding_workspace_id ? "pending" : "reviewed";
    if (!workspaceId)
      setWorkspace(
        (
          workspaces.data.find((item) => item.id === profile.data.onboarding_workspace_id) ??
          workspaces.data.find((item) => item.kind === "personal") ??
          workspaces.data[0]
        )?.id ?? "",
      );
  }, [workspaces.data, workspaceId, profile.data, initialWorkspaceFlow]);
  useEffect(() => {
    if (!observedSavedChoice || busy || workspaceChoiceState.current !== "pending") return;
    setWorkspace(observedSavedChoice);
    setCreatingTeam(false);
    setStep("workspace");
    if (!savedChoiceIsKnown) void reloadWorkspaceChoices();
  }, [observedSavedChoice, busy, savedChoiceIsKnown, reloadWorkspaceChoices]);
  const path = { workspace_id: workspaceId };
  const projects = useQuery({
    queryKey: ["projects", workspaceId],
    enabled: !!workspace,
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects", { params: { path } })),
  });
  const project = projects.data?.find((item) => item.id === projectId);
  const intention = project ? projectStart(project.source) : selectedStart;
  const projectSteps: Step[] =
    intention === "idea" && step !== "github" && !project?.repo_url ? ["start", "project", "model", "ready"] : ["start", "project", "github", "model", "ready"];
  const flowSteps: Step[] = addingProject ? projectSteps : ["workspace", ...projectSteps];
  const needsWorkspaceChoice = !addingProject && !query.has("workspace") && !query.has("project") && profile.data?.onboarding_workspace_id == null;
  const github = useQuery({
    queryKey: ["onboarding-github", workspaceId],
    enabled: !!workspace && step === "github",
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/github", { params: { path } })),
  });
  const repos = useQuery({
    queryKey: ["onboarding-repos", workspaceId],
    enabled: !!workspace && step === "github" && github.data?.configured === true,
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/github/repos", { params: { path } })),
  });
  const repositoryReady = useQuery({
    queryKey: ["repository-readiness", workspaceId, projectId, project?.repo_url],
    enabled: !!project?.repo_url && step === "github",
    retry: false,
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/readiness", {
          params: { path: { workspace_id: workspaceId, project_id: projectId } },
        }),
      ),
  });
  const models = useQuery({ queryKey: ["my-models"], enabled: signedIn, queryFn: myModels });
  const access = useQuery({
    queryKey: ["model-access", workspaceId],
    enabled: !!workspace && (step === "model" || step === "ready"),
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/model-access", { params: { path } })),
  });
  const move = (next: Step, id = projectId, ws = workspaceId, startingPoint = intention) => {
    setError("");
    setStep(next);
    const params = new URLSearchParams({ workspace: ws, step: next });
    if (id) params.set("project", id);
    if (addingProject) params.set("mode", "project");
    if (startingPoint) params.set("intent", startingPoint);
    history.replaceState(history.state, "", `/onboarding?${params}`);
  };
  const perform = async (action: () => Promise<void>) => {
    if (submission.current) return;
    submission.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      submission.current = false;
      setBusy(false);
    }
  };
  const create = () =>
    perform(async () => {
      if (!intention) throw new Error("Choose how you want to start this project.");
      if (intention === "new" && !description.trim()) throw new Error("Describe the goal before setting up the new codebase.");
      if (!name.trim() || !/^[A-Z][A-Z0-9]{1,9}$/.test(key))
        throw new Error("Enter a project name and a key of 2–10 letters or digits, starting with a letter.");
      // Keep the same key on retries. Refresh after an uncertain response so saved work can be resumed explicitly.
      try {
        const created = await unwrap(
          api.POST("/v1/workspaces/{workspace_id}/projects", {
            params: { path },
            body: {
              name: name.trim(),
              key,
              source: PROJECT_STARTS.find((item) => item.id === intention)!.source,
              description: description.trim(),
              access: workspace?.kind === "organization" ? accessLevel : "workspace",
            },
          }),
        );
        setProject(created.id);
        move(intention === "idea" ? "model" : "github", created.id);
        await projects.refetch();
      } catch (cause) {
        await projects.refetch();
        throw cause;
      }
    });
  const chooseWorkspace = (kind: "personal" | "organization", rename: boolean) =>
    perform(async () => {
      setStep("workspace");
      const typed = (displayName ?? "").trim();
      if (rename && typed && typed !== profile.data?.display_name) {
        await unwrap(api.PATCH("/v1/me", { body: { display_name: typed } }));
      }
      const body = { kind, name: kind === "organization" ? teamName.trim() : null };
      let chosen;
      try {
        chosen = await unwrap(api.POST("/v1/me/onboarding-workspace", { body }));
      } catch (cause) {
        // The response may have been lost after commit; recover only the same saved choice.
        const saved = await profile.refetch();
        const available = await workspaces.refetch();
        chosen = available.data?.find((item) => item.id === saved.data?.onboarding_workspace_id);
        if (!chosen) throw cause;
        if (chosen.kind !== kind || (kind === "organization" && chosen.name !== body.name)) {
          setWorkspace(chosen.id);
          setCreatingTeam(false);
          move("workspace", "", chosen.id);
          throw new Error("A workspace choice is already saved. Review it before continuing.");
        }
      }
      workspaceChoiceState.current = "reviewed";
      setWorkspace(chosen.id);
      setCreatingTeam(false);
      await workspaces.refetch();
      await profile.refetch();
      move("start", "", chosen.id);
    });
  const connectRepo = () =>
    perform(async () => {
      const repo = repos.data?.find((item) => `${item.installation_ref}:${item.github_repo_id}` === repoId);
      if (!repo || !project) throw new Error("Select an available repository and project.");
      await unwrap(
        api.PUT("/v1/workspaces/{workspace_id}/projects/{project_id}/repository", {
          params: { path: { ...path, project_id: project.id } },
          body: { installation_ref: repo.installation_ref, github_repo_id: repo.github_repo_id },
        }),
      );
      await projects.refetch();
      move("model");
    });
  const saveKey = () =>
    perform(async () => {
      await myKeySaved(provider, apiKey.trim());
      setApiKey("");
      await models.refetch();
      await access.refetch();
    });
  if (!signedIn)
    return (
      <Frame art="workspace" center>
        <Head title="Set up Dotrix" sub="Sign in or create an account to save your first project." />
        <div className="onb2-acts">
          <a href={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} className="btn btn-ghost onb2-btn">
            Sign in
          </a>
          <a className="btn btn-primary onb2-btn" href={`/signup?next=${encodeURIComponent(location.pathname + location.search)}`}>
            Create an account
          </a>
        </div>
      </Frame>
    );
  if (workspaces.isLoading || profile.isLoading)
    return (
      <Frame art="workspace" center>
        <p role="status" className="muted">
          Loading your workspaces…
        </p>
      </Frame>
    );
  if (workspaces.isError || profile.isError)
    return (
      <Frame art="workspace" center>
        <p role="alert" className="err">
          {errorMessage(workspaces.error ?? profile.error)}
        </p>
        <div className="onb2-acts">
          <button
            className="btn btn-primary onb2-btn"
            onClick={() => {
              void workspaces.refetch();
              void profile.refetch();
            }}
          >
            Try again
          </button>
        </div>
      </Frame>
    );
  const ownWorkspace =
    workspaces.data?.find((item) => item.kind === "personal" && item.role === "owner") ??
    workspaces.data?.find((item) => item.role === "owner" || item.role === "admin");
  const ownSetupHref = `/onboarding?${new URLSearchParams(ownWorkspace ? { mode: "project", workspace: ownWorkspace.id } : { mode: "project", team: "1" })}`;
  if (workspace && workspace.role !== "owner" && workspace.role !== "admin" && !creatingTeam && !needsWorkspaceChoice)
    return (
      <Frame art="workspace" center>
        <Head
          title="Open your team workspace"
          sub={`You already belong to ${workspace.name}. Only owners and admins create projects; you can use the projects shared with you.`}
        />
        <div className="onb2-acts">
          <a className="btn btn-ghost onb2-btn" href={ownSetupHref}>
            Set up a project in your own workspace
          </a>
          <a className="btn btn-primary onb2-btn" href={`/w/${workspace.slug}`}>
            Open workspace
          </a>
        </div>
      </Frame>
    );
  const duplicateKey = projects.data?.some((item) => item.key === key);
  const existingTeam = workspaces.data?.find((item) => item.kind === "organization" && item.name.toLowerCase() === teamName.trim().toLowerCase());
  const modelReady =
    !!access.data?.ready &&
    !!((models.data?.default_model && access.data.models.includes(models.data.default_model)) || (project && access.data.models.includes(project.model)));
  const current: Step =
    needsWorkspaceChoice || observedSavedChoice || (step === "workspace" && !addingProject)
      ? "workspace"
      : !project
        ? step === "start" || !intention
          ? "start"
          : "project"
        : step === "start"
          ? "project"
          : step;
  const discussionStart = project?.repo_url ? "existing" : intention;
  const at = flowSteps.indexOf(current);
  const back = at > 0 && current !== "ready" ? flowSteps[at - 1] : null;
  const typedName = displayName ?? profile.data?.display_name ?? "";
  // Where to create the project: shown only when there's a choice to make.
  const choosable = workspaces.data?.filter((item) => item.role === "owner" || item.role === "admin") ?? [];
  const dots = (
    <nav aria-label="Onboarding progress" className="onb2-dots">
      <ol>
        {flowSteps.map((item, index) => (
          <li key={item} aria-current={item === current ? "step" : undefined} className={index < at ? "done" : index === at ? "on" : ""}>
            <span className="sr-only">
              {stepNames[item]}
              {index < at ? " completed" : ""}
            </span>
          </li>
        ))}
      </ol>
      <span className="sr-only">
        Step {at + 1} of {flowSteps.length}: {stepNames[current]}
      </span>
    </nav>
  );
  return (
    <Frame art={current} projectKey={project?.key ?? key} dots={dots}>
      {back && (
        <button className="onb2-back" disabled={busy} onClick={() => move(back)}>
          <Ic n="chevron-left" s={14} />
          Back
        </button>
      )}
      {current === "workspace" &&
        (needsWorkspaceChoice ? (
          <form
            className="onb2-form"
            onSubmit={(event) => {
              event.preventDefault();
              void chooseWorkspace(workspaceKind, true);
            }}
          >
            <Head title="Set up your profile" sub="Choose how you'll appear in Dotrix." />
            <fieldset disabled={busy} className="onb2-fields">
              <label className="field">
                Your name
                <span className="onb2-name">
                  <span className="onb2-avatar" aria-hidden>
                    {(typedName.trim()[0] ?? "?").toUpperCase()}
                  </span>
                  <input
                    className="input onb2-input"
                    value={typedName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    aria-label="Your name"
                    maxLength={100}
                    autoComplete="name"
                    required
                  />
                </span>
              </label>
              {workspaceKind === "organization" ? (
                <label className="field">
                  Organisation name
                  <input
                    className="input onb2-input"
                    value={teamName}
                    onChange={(event) => setTeamName(event.target.value)}
                    aria-label="Organisation name"
                    maxLength={100}
                    autoComplete="organization"
                    required
                    autoFocus
                  />
                  <span className="onb2-hint">
                    A shared workspace for your team. Your sign-in and model keys stay yours.{" "}
                    <button type="button" className="link" onClick={() => setWorkspaceKind("personal")}>
                      Just me
                    </button>
                  </span>
                </label>
              ) : (
                <p className="onb2-hint">
                  Your projects start in your own private workspace.{" "}
                  <button type="button" className="link" onClick={() => setWorkspaceKind("organization")}>
                    Setting up for a team?
                  </button>
                </p>
              )}
            </fieldset>
            <div className="onb2-acts">
              <button type="button" className="btn btn-ghost onb2-btn" disabled={busy} onClick={() => void chooseWorkspace("personal", false)}>
                Skip
              </button>
              <button
                className="btn btn-primary onb2-btn"
                type="submit"
                disabled={busy || !typedName.trim() || (workspaceKind === "organization" && !teamName.trim())}
              >
                Continue
              </button>
            </div>
          </form>
        ) : summaryWorkspace ? (
          <>
            <Head
              title="Your workspace is saved"
              sub={`${summaryWorkspace.name} · ${summaryWorkspace.kind === "organization" ? "Organisation" : "Personal"}. Continue to your first project.`}
            />
            <div className="onb2-acts">
              <button
                className="btn btn-primary onb2-btn"
                disabled={busy}
                onClick={() => {
                  workspaceChoiceState.current = "reviewed";
                  if (observedSavedChoice) {
                    setWorkspace(summaryWorkspace.id);
                    setProject("");
                    move("start", "", summaryWorkspace.id);
                  } else move("start");
                }}
              >
                Continue
              </button>
            </div>
          </>
        ) : (
          <>
            <Head
              title="Your workspace is saved"
              sub={
                workspaces.isFetching ? "Loading the saved workspace…" : "The saved workspace isn't available right now. Refresh it, or use your own workspace."
              }
            />
            <div className="onb2-acts">
              <a className="btn btn-ghost onb2-btn" href={ownSetupHref}>
                Use my own workspace
              </a>
              <button
                className="btn btn-primary onb2-btn"
                disabled={workspaces.isFetching}
                onClick={() => {
                  void profile.refetch();
                  void workspaces.refetch();
                }}
              >
                Refresh
              </button>
            </div>
          </>
        ))}
      {current === "start" && (
        <form
          className="onb2-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (intention && workspace) move("project");
          }}
        >
          <Head title="How do you want to start?" sub="Pick what fits today. You can connect code or change direction later." />
          <fieldset className="onb2-fields" disabled={busy}>
            <legend className="sr-only">Starting point</legend>
            <div className="onb2-choices">
              {PROJECT_STARTS.map((item) => (
                <label className={`onb2-choice ${intention === item.id ? "on" : ""}`} key={item.id}>
                  <input
                    type="radio"
                    name="project-start"
                    value={item.id}
                    aria-label={item.label}
                    checked={intention === item.id}
                    onChange={() => {
                      setStart(item.id);
                      const params = new URLSearchParams(location.search);
                      params.set("intent", item.id);
                      history.replaceState(history.state, "", `/onboarding?${params}`);
                    }}
                  />
                  <span className="onb2-choice-i">
                    <Ic n={item.icon} s={18} />
                  </span>
                  <span className="onb2-choice-t">
                    <b>{item.label}</b>
                    <span>{item.description}</span>
                  </span>
                </label>
              ))}
            </div>
            {(choosable.length > 1 || addingProject) && (
              <label className="field">
                Workspace
                <select
                  aria-label="Workspace"
                  className="select onb2-input"
                  value={workspaceId}
                  onChange={(event) => {
                    setWorkspace(event.target.value);
                    setProject("");
                    move("start", "", event.target.value);
                  }}
                >
                  {workspaces.data?.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {workspaceId && workspaces.isSuccess && !workspace && <p role="alert">This workspace is unavailable. Select another workspace to continue.</p>}
            {addingProject &&
              (creatingTeam ? (
                <div className="onb2-team">
                  <label className="field">
                    Team workspace name
                    <input className="input onb2-input" value={teamName} onChange={(event) => setTeamName(event.target.value)} maxLength={100} />
                  </label>
                  {existingTeam && <p role="status">A team workspace with this name is already saved.</p>}
                  <div className="onb2-acts">
                    <button type="button" className="btn btn-ghost onb2-btn" onClick={() => setCreatingTeam(false)}>
                      Cancel
                    </button>
                    {existingTeam ? (
                      <button
                        type="button"
                        className="btn btn-secondary onb2-btn"
                        onClick={() => {
                          setWorkspace(existingTeam.id);
                          setProject("");
                          setCreatingTeam(false);
                          move("start", "", existingTeam.id);
                        }}
                      >
                        Use saved team workspace
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="btn btn-secondary onb2-btn"
                      disabled={!teamName.trim() || !!existingTeam}
                      onClick={() =>
                        void perform(async () => {
                          try {
                            const created = await unwrap(api.POST("/v1/workspaces", { body: { name: teamName.trim(), kind: "organization" } }));
                            setWorkspace(created.id);
                            setProject("");
                            move("start", "", created.id);
                            setCreatingTeam(false);
                            await workspaces.refetch();
                          } catch (cause) {
                            await workspaces.refetch();
                            throw cause;
                          }
                        })
                      }
                    >
                      Create team workspace
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" className="link onb2-hint" onClick={() => setCreatingTeam(true)}>
                  Create a team workspace
                </button>
              ))}
          </fieldset>
          <div className="onb2-acts">
            <button className="btn btn-primary onb2-btn" type="submit" disabled={busy || !intention || !workspace || creatingTeam}>
              Continue
            </button>
          </div>
        </form>
      )}
      {current === "project" && (
        <>
          <Head
            title={project ? `${project.name} is saved` : addingProject || !!projects.data?.length ? "Create a project" : "Create your first project"}
            sub={
              project
                ? project.description || "Continue where you left off."
                : intention === "idea"
                  ? "A working title is enough. Explore it with Nova before deciding what to build."
                  : intention === "new"
                    ? "Name it and describe the goal. The repository comes next."
                    : "Give the repository a home in Dotrix. You'll pick it on GitHub next."
            }
          />
          {projectId && projects.isLoading ? (
            <p role="status">Loading your saved project…</p>
          ) : project ? (
            <div className="onb2-acts">
              <button className="btn btn-primary onb2-btn" onClick={() => move(intention === "idea" && !project.repo_url ? "model" : "github")}>
                Continue setup
              </button>
            </div>
          ) : (
            <form
              className="onb2-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (!busy && !duplicateKey && workspace && projects.isSuccess && intention) void create();
              }}
            >
              {projectId && <p role="alert">This saved project is unavailable. Choose an existing project or create one.</p>}
              <fieldset className="onb2-fields" disabled={busy}>
                <label className="field">
                  Project name
                  <input
                    className="input onb2-input"
                    value={name}
                    maxLength={100}
                    autoFocus
                    onChange={(event) => {
                      setName(event.target.value);
                      if (!keyEdited)
                        setKey(
                          event.target.value
                            .toUpperCase()
                            .replace(/[^A-Z0-9]/g, "")
                            .slice(0, 10),
                        );
                    }}
                  />
                </label>
                <label className="field">
                  Project key
                  <input
                    className="input onb2-input mono"
                    value={key}
                    aria-label="Project key"
                    maxLength={10}
                    onChange={(event) => {
                      setKeyEdited(true);
                      setKey(event.target.value.toUpperCase());
                    }}
                    placeholder="APP"
                  />
                  <span className="onb2-hint">
                    Tasks are numbered {key || "APP"}-1, {key || "APP"}-2… 2–10 letters or digits.
                  </span>
                </label>
                {duplicateKey && <p role="alert">A project with this key is already saved. Continue setting it up below, or choose a different key.</p>}
                <label className="field">
                  {intention === "new" ? "Project goal" : "Description (optional)"}
                  <textarea
                    className="textarea onb2-input"
                    required={intention === "new"}
                    value={description}
                    maxLength={500}
                    rows={3}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
                {workspace?.kind === "organization" && (
                  <label className="field">
                    Who can see it
                    <select
                      aria-label="Project access"
                      className="select onb2-input"
                      value={accessLevel}
                      onChange={(event) => setAccessLevel(event.target.value as "workspace" | "restricted")}
                    >
                      <option value="workspace">Everyone in {workspace.name}</option>
                      <option value="restricted">Only owners, admins and people added</option>
                    </select>
                  </label>
                )}
              </fieldset>
              <div className="onb2-acts">
                <button
                  className="btn btn-primary onb2-btn"
                  disabled={
                    busy ||
                    !intention ||
                    (intention === "new" && !description.trim()) ||
                    !workspace ||
                    !projects.isSuccess ||
                    duplicateKey ||
                    !name.trim() ||
                    !/^[A-Z][A-Z0-9]{1,9}$/.test(key)
                  }
                  type="submit"
                >
                  {busy ? "Creating project…" : "Create project"}
                </button>
              </div>
              {!!projects.data?.length && (
                <label className="field onb2-resume">
                  Continue setting up an existing project
                  <select
                    aria-label="Continue setting up an existing project"
                    className="select onb2-input"
                    disabled={busy}
                    value=""
                    onChange={(event) => {
                      const saved = projects.data?.find((item) => item.id === event.target.value);
                      if (!saved) return;
                      const start = projectStart(saved.source);
                      setProject(saved.id);
                      move(start === "idea" ? "model" : "github", saved.id, workspaceId, start);
                    }}
                  >
                    <option value="">Choose a project</option>
                    {projects.data.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </form>
          )}
          {projects.isError && (
            <p role="alert">
              {errorMessage(projects.error)}{" "}
              <button className="link" onClick={() => void projects.refetch()}>
                Try again
              </button>
            </p>
          )}
        </>
      )}
      {current === "github" && (
        <>
          <Head
            title="Connect GitHub"
            sub={`Bring ${project?.name ?? "your project"}'s code in. Signing in with GitHub doesn't grant repository access; this does.`}
          />
          <ul className="onb2-features">
            <li>
              <b>Kai codes on a branch</b>
              <span>Approved tasks become pull requests in your repository.</span>
            </li>
            <li>
              <b>Answers from your code</b>
              <span>Nova and the specialists read the repository and cite the files.</span>
            </li>
            <li>
              <b>Reviews before you merge</b>
              <span>Juno reviews each pull request. The merge is always yours.</span>
            </li>
          </ul>
          {github.isLoading && <p role="status">Checking GitHub…</p>}
          {github.isError && (
            <p role="alert">
              {errorMessage(github.error)}{" "}
              <button className="link" onClick={() => void github.refetch()}>
                Try again
              </button>
            </p>
          )}
          {github.data && !github.data.configured && (
            <p className="onb2-hint">GitHub isn&apos;t set up on this server yet. Start with documents; you can connect a repository later.</p>
          )}
          {github.data?.configured && (
            <div className="onb2-fields">
              {!!repos.data?.length && (
                <label className="field">
                  Repository
                  <select aria-label="Repository" className="select onb2-input" value={repoId} onChange={(event) => setRepo(event.target.value)}>
                    <option value="">Select a repository</option>
                    {repos.data.map((repo) => (
                      <option key={`${repo.installation_ref}:${repo.github_repo_id}`} value={`${repo.installation_ref}:${repo.github_repo_id}`}>
                        {repo.full_name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <RepositoryCreate
                key={`${workspaceId}:${projectId}`}
                workspaceId={workspaceId}
                installations={github.data.installations}
                repositories={repos.data ?? []}
                refresh={async () => {
                  const result = await repos.refetch();
                  if (result.error) throw result.error;
                }}
                onCreated={(repo) => {
                  queryClient.setQueryData<Schemas["RepoOption"][]>(["onboarding-repos", workspaceId], (items = []) => [
                    ...items.filter((item) => item.github_repo_id !== repo.github_repo_id),
                    repo,
                  ]);
                  setRepo(`${repo.installation_ref}:${repo.github_repo_id}`);
                }}
              />
              <button
                className="link onb2-hint"
                disabled={busy || repos.isFetching}
                onClick={() =>
                  void perform(async () => {
                    const status = await github.refetch();
                    if (status.error) throw status.error;
                    const result = await repos.refetch();
                    if (result.error) throw result.error;
                  })
                }
              >
                Refresh repositories
              </button>
            </div>
          )}
          {repos.isError && (
            <p role="alert">
              {errorMessage(repos.error)}{" "}
              <button className="link" onClick={() => void repos.refetch()}>
                Try again
              </button>
            </p>
          )}
          {project?.repo_url && <p role="status">Connected: {project.repo_url}</p>}
          <div className="onb2-acts">
            {project?.repo_url ? (
              <button className="btn btn-primary onb2-btn" disabled={busy} onClick={() => move("model")}>
                Continue
              </button>
            ) : (
              <>
                <button className="btn btn-ghost onb2-btn" disabled={busy} onClick={() => move("model")} aria-label="Continue with documents only">
                  Skip
                </button>
                {repoId ? (
                  <button className="btn btn-primary onb2-btn" disabled={busy} onClick={() => void connectRepo()}>
                    Use repository
                  </button>
                ) : (
                  github.data?.install_url && (
                    <button
                      className="btn btn-primary onb2-btn"
                      disabled={busy}
                      onClick={() => {
                        move("github");
                        installGitHub(github.data as Schemas["GitHubStatus"], workspaceId, location.pathname + location.search);
                      }}
                    >
                      <Ic n="github" s={16} />
                      Connect GitHub App
                    </button>
                  )
                )}
              </>
            )}
          </div>
        </>
      )}
      {current === "model" && (
        <>
          <Head
            title="Connect your model"
            sub="Your own provider key powers Nova, the specialists and Kai. It's stored encrypted and used only for your runs."
          />
          {models.isError && (
            <p role="alert">
              {errorMessage(models.error)}{" "}
              <button className="link" onClick={() => void models.refetch()}>
                Try again
              </button>
            </p>
          )}
          {access.data?.ready && <p role="status">A personal model connection is available.</p>}
          {access.data && !access.data.can_store_keys && (
            <p role="alert">Encrypted key storage isn&apos;t available here. Ask your administrator to configure it.</p>
          )}
          <div className="onb2-fields">
            <label className="field">
              Model provider
              <select
                aria-label="Model provider"
                disabled={busy || !models.data}
                className="select onb2-input"
                value={provider}
                onChange={(event) => {
                  setProvider(event.target.value);
                  setApiKey("");
                }}
              >
                {models.data?.keys.map((item) => (
                  <option key={item.provider} value={item.provider}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Model API key
              <span className="onb2-name">
                <input
                  className="input onb2-input"
                  type="password"
                  value={apiKey}
                  aria-label="Model API key"
                  autoComplete="off"
                  maxLength={400}
                  spellCheck={false}
                  onChange={(event) => setApiKey(event.target.value)}
                />
                <button
                  className="btn btn-secondary onb2-btn"
                  disabled={busy || !access.data?.can_store_keys || apiKey.trim().length < 20}
                  onClick={() => void saveKey()}
                >
                  {busy ? "Saving…" : "Save personal key"}
                </button>
              </span>
            </label>
            {!!access.data?.models.length && (
              <label className="field">
                Default model
                <select
                  aria-label="Default model"
                  disabled={busy}
                  className="select onb2-input"
                  value={models.data?.default_model ?? ""}
                  onChange={(event) =>
                    void perform(async () => {
                      await myDefaultModelSaved(event.target.value || null);
                      await models.refetch();
                    })
                  }
                >
                  <option value="">Choose a default model</option>
                  {access.data.models.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {access.isError && (
            <p role="alert">
              {errorMessage(access.error)}{" "}
              <button className="link" onClick={() => void access.refetch()}>
                Try again
              </button>
            </p>
          )}
          <div className="onb2-acts">
            {access.data?.ready ? (
              <button className="btn btn-primary onb2-btn" disabled={busy || !modelReady} onClick={() => move("ready")}>
                Continue
              </button>
            ) : (
              <button className="btn btn-ghost onb2-btn" disabled={busy} onClick={() => move("ready")} aria-label="Set up models later">
                Skip
              </button>
            )}
          </div>
        </>
      )}
      {current === "ready" && (
        <>
          <Head
            title={discussionStart === "idea" ? "Your idea has a home" : "Your project is saved"}
            sub={`${project?.name ?? "Your project"} is in ${workspace?.name ?? "your workspace"}. Here's what's ready, and a good first step.`}
          />
          {project && workspace && <ProjectReadiness workspaceId={workspace.id} projectId={project.id} slug={workspace.slug} projectKey={project.key} />}
          {project?.repo_url && (
            <section aria-label="Repository readiness" className="onb2-fields">
              {repositoryReady.isFetching && <p role="status">Checking the repository&apos;s default branch…</p>}
              {repositoryReady.data?.ready && !repositoryReady.isError && !repositoryReady.isFetching && (
                <p role="status">
                  Ready for a new coding branch: {repositoryReady.data.full_name} · {repositoryReady.data.default_branch} ·{" "}
                  {repositoryReady.data.commit_sha?.slice(0, 7)}.
                </p>
              )}
              {repositoryReady.data && !repositoryReady.data.ready && <p role="alert">{repositoryReady.data.reason}</p>}
              {repositoryReady.isError && <p role="alert">Couldn&apos;t verify the repository: {errorMessage(repositoryReady.error)}</p>}
              <button className="link onb2-hint" disabled={repositoryReady.isFetching} onClick={() => void repositoryReady.refetch()}>
                {repositoryReady.data || repositoryReady.isError ? "Check repository again" : "Check repository"}
              </button>
            </section>
          )}
          <div className="onb2-acts onb2-acts-wrap">
            {modelReady ? (
              <a className="btn btn-secondary onb2-btn" href={projectDiscussionHref(workspace!.slug, project!.key, discussionStart!)}>
                {discussionStart === "idea" ? "Explore with Nova" : discussionStart === "new" ? "Plan with Nova" : "Discuss with Nova"}
              </a>
            ) : (
              <button className="btn btn-secondary onb2-btn" disabled={busy} onClick={() => move("model")}>
                Set up Nova
              </button>
            )}
            {project?.repo_url && intention === "existing" && (
              <a className="btn btn-secondary onb2-btn" href={`/w/${workspace!.slug}/p/${project.key}/knowledge?view=coverage`}>
                Understand repository first
              </a>
            )}
            {modelReady && repositoryReady.data?.ready && !repositoryReady.isError && !repositoryReady.isFetching && intention === "new" && (
              <a className="btn btn-secondary onb2-btn" href={projectImplementationHref(workspace!.slug, project!.key)}>
                Plan first implementation
              </a>
            )}
            <a className="btn btn-primary onb2-btn" href={`/w/${workspace?.slug}/p/${project?.key}/overview`}>
              Open project
            </a>
          </div>
        </>
      )}
      {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}
      {workspace && current !== "ready" && (
        <a className="onb2-later" href={`/w/${workspace.slug}`}>
          {project ? "Finish setup later" : "Back to workspace"}
        </a>
      )}
    </Frame>
  );
}

function Head({ title, sub }: { title: string; sub: string }) {
  return (
    <header className="onb2-head">
      <h1>{title}</h1>
      <p>{sub}</p>
    </header>
  );
}

/** The two columns: the step, its progress dots under it, and a quiet preview of what it sets up. */
function Frame({
  children,
  dots,
  art,
  projectKey = "",
  center = false,
}: {
  children: ReactNode;
  dots?: ReactNode;
  art: Step;
  projectKey?: string;
  center?: boolean;
}) {
  return (
    <div className="onb2">
      <main className="onb2-main">
        <div className={`onb2-col ${center ? "center" : ""}`}>{children}</div>
        {dots}
      </main>
      <div className="onb2-art" aria-hidden>
        <Preview key={art} step={art} projectKey={projectKey} />
      </div>
    </div>
  );
}

const TEAM = [...AGENTS.filter((agent) => agent.builtIn).slice(0, 6), { ...CODING_AGENT, role: "Coding" }];

function Preview({ step, projectKey }: { step: Step; projectKey: string }) {
  const k = projectKey || "APP";
  if (step === "start")
    return (
      <div className="onb2-pv">
        {PROJECT_STARTS.map((item) => (
          <div key={item.id} className="onb2-pv-row">
            <Ic n={item.icon} s={22} />
            <span>{item.label}</span>
          </div>
        ))}
      </div>
    );
  if (step === "project")
    return (
      <div className="onb2-pv">
        {["Define the first milestone", "Draft the requirements", "Set up the repository"].map((title, index) => (
          <div key={title} className="onb2-pv-row">
            <span className="mono onb2-pv-key">
              {k}-{index + 1}
            </span>
            <span>{title}</span>
          </div>
        ))}
      </div>
    );
  if (step === "github")
    return (
      <div className="onb2-pv mono">
        <div className="onb2-pv-row">
          <Ic n="github" s={22} />
          <span>dotrix/{k.toLowerCase()}-1</span>
        </div>
        <div className="onb2-pv-row">
          <Ic n="code" s={22} />
          <span>+42 −7 · checks passed</span>
        </div>
        <div className="onb2-pv-row">
          <Ic n="check" s={22} />
          <span>Reviewed by Juno</span>
        </div>
      </div>
    );
  if (step === "model" || step === "ready")
    return (
      <div className="onb2-pv">
        {TEAM.map((agent) => (
          <div key={agent.name} className="onb2-pv-row">
            <Face c={agent.c} size={30} />
            <span>{agent.name}</span>
            <span className="onb2-pv-role">{agent.role}</span>
          </div>
        ))}
      </div>
    );
  return (
    <div className="onb2-pv">
      {(
        [
          ["home", "Home"],
          ["inbox", "Inbox"],
          ["chat", "Chat"],
          ["code", "Codes"],
          ["folder", "Projects"],
        ] as const
      ).map(([icon, label]) => (
        <div key={label} className="onb2-pv-row">
          <Ic n={icon} s={22} />
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}
