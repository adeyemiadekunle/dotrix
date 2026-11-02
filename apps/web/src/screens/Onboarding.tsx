import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage, hasSession, unwrap, type Schemas } from "@/lib/api";
import { installGitHub, myDefaultModelSaved, myKeySaved, myModels } from "../data/account";
import { Ic } from "../core/icons";

type Step = "project" | "github" | "model" | "ready";
const steps: Step[] = ["project", "github", "model", "ready"];

/** Only server-confirmed workspace/project IDs are retained across redirects. Keys stay in memory. */
export function Onboarding() {
  const query = new URLSearchParams(location.search);
  const addingProject = query.get("mode") === "project";
  const submission = useRef(false);
  const [workspaceId, setWorkspace] = useState(query.get("workspace") ?? "");
  const [projectId, setProject] = useState(query.get("project") ?? "");
  const [step, setStep] = useState<Step>(steps.includes(query.get("step") as Step) ? (query.get("step") as Step) : "project");
  const [teamName, setTeamName] = useState("");
  const [creatingTeam, setCreatingTeam] = useState(query.get("team") === "1");
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
  const workspaces = useQuery({ queryKey: ["workspaces"], enabled: signedIn, queryFn: () => unwrap(api.GET("/v1/workspaces")) });
  const workspace = workspaces.data?.find((item) => item.id === workspaceId);
  useEffect(() => {
    if (!workspaces.data) return;
    if (!workspaceId) setWorkspace((workspaces.data.find((item) => item.kind === "personal") ?? workspaces.data[0])?.id ?? "");
  }, [workspaces.data, workspaceId]);
  const path = { workspace_id: workspaceId };
  const projects = useQuery({
    queryKey: ["projects", workspaceId],
    enabled: !!workspace,
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects", { params: { path } })),
  });
  const project = projects.data?.find((item) => item.id === projectId);
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
  const models = useQuery({ queryKey: ["my-models"], enabled: signedIn, queryFn: myModels });
  const access = useQuery({
    queryKey: ["model-access", workspaceId],
    enabled: !!workspace && (step === "model" || step === "ready"),
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/model-access", { params: { path } })),
  });
  const move = (next: Step, id = projectId, ws = workspaceId) => {
    setError("");
    setStep(next);
    const params = new URLSearchParams({ workspace: ws, step: next });
    if (id) params.set("project", id);
    if (addingProject) params.set("mode", "project");
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
      if (!name.trim() || !/^[A-Z][A-Z0-9]{1,9}$/.test(key))
        throw new Error("Enter a project name and a key of 2–10 letters or digits, starting with a letter.");
      // Keep the same key on retries. Refresh after an uncertain response so saved work can be resumed explicitly.
      try {
        const created = await unwrap(
          api.POST("/v1/workspaces/{workspace_id}/projects", {
            params: { path },
            body: { name: name.trim(), key, source: "docs_only", description: description.trim(), access: accessLevel },
          }),
        );
        setProject(created.id);
        move("github", created.id);
        await projects.refetch();
      } catch (cause) {
        await projects.refetch();
        throw cause;
      }
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
      <div className="auth-card">
        <h1>Set up your workspace</h1>
        <p>Sign in or create an account to save your first project.</p>
        <a className="btn btn-primary" href={`/signup?next=${encodeURIComponent(location.pathname + location.search)}`}>
          Create an account
        </a>
        <a href={`/login?next=${encodeURIComponent(location.pathname + location.search)}`}>Sign in</a>
      </div>
    );
  if (workspaces.isLoading)
    return (
      <div className="auth-card" role="status">
        Loading your workspaces…
      </div>
    );
  if (workspaces.isError)
    return (
      <div className="auth-card" role="alert">
        {errorMessage(workspaces.error)}
        <button onClick={() => void workspaces.refetch()}>Try again</button>
      </div>
    );
  if (workspace && workspace.role !== "owner" && workspace.role !== "admin")
    return (
      <div className="auth-card">
        <h1>Open your team workspace</h1>
        <p>You already belong to {workspace.name}. Only owners and admins create projects; you can use the projects shared with you.</p>
        <a className="btn btn-primary" href={`/w/${workspace.slug}`}>
          Open workspace
        </a>
        <a href="/onboarding">Set up a project in your own workspace</a>
      </div>
    );
  const duplicateKey = projects.data?.some((item) => item.key === key);
  const existingTeam = workspaces.data?.find((item) => item.kind === "organization" && item.name.toLowerCase() === teamName.trim().toLowerCase());
  const modelReady =
    !!access.data?.ready &&
    !!((models.data?.default_model && access.data.models.includes(models.data.default_model)) || (project && access.data.models.includes(project.model)));
  const current: Step = !project ? "project" : step;
  return (
    <div className="auth-card onb" style={{ maxWidth: 560 }}>
      <div className="steps" aria-label={`Step ${steps.indexOf(current) + 1} of 4`}>
        {steps.map((item) => (
          <i key={item} className={steps.indexOf(item) <= steps.indexOf(current) ? "on" : ""} />
        ))}
      </div>
      <p className="faint">Project · GitHub · Model · Start working</p>
      {current === "project" && (
        <>
          <h1>{addingProject || !!projects.data?.length ? "Create a project" : "Create your first project"}</h1>
          <p className="sub">Give your work a home. You can connect a repository in the next step.</p>
          <label className="field">
            Workspace
            <select
              aria-label="Workspace"
              className="select"
              value={workspaceId}
              disabled={busy || (!!projectId && !!project)}
              onChange={(event) => {
                setWorkspace(event.target.value);
                setProject("");
                move("project", "", event.target.value);
              }}
            >
              {workspaces.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          {workspaceId && workspaces.isSuccess && !workspace && <p role="alert">This workspace is unavailable. Select another workspace to continue.</p>}
          {creatingTeam ? (
            <>
              <label className="field">
                Team workspace name
                <input className="input" disabled={busy} value={teamName} onChange={(event) => setTeamName(event.target.value)} maxLength={100} />
              </label>
              <button
                className="btn"
                disabled={busy || !teamName.trim() || !!existingTeam}
                onClick={() =>
                  void perform(async () => {
                    try {
                      const created = await unwrap(api.POST("/v1/workspaces", { body: { name: teamName.trim(), kind: "organization" } }));
                      setWorkspace(created.id);
                      setProject("");
                      move("project", "", created.id);
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
              {existingTeam && (
                <>
                  <p role="status">A team workspace with this name is already saved.</p>
                  <button
                    className="btn btn-secondary"
                    disabled={busy}
                    onClick={() => {
                      setWorkspace(existingTeam.id);
                      setProject("");
                      setCreatingTeam(false);
                      move("project", "", existingTeam.id);
                    }}
                  >
                    Use saved team workspace
                  </button>
                </>
              )}
              <button className="btn btn-ghost" disabled={busy} onClick={() => setCreatingTeam(false)}>
                Cancel
              </button>
            </>
          ) : (
            <button className="btn btn-ghost" disabled={busy} onClick={() => setCreatingTeam(true)}>
              Create a team workspace
            </button>
          )}
          {projectId && projects.isLoading ? (
            <p role="status">Loading your saved project…</p>
          ) : (
            <>
              {projectId && !project && <p role="alert">This saved project is unavailable. Choose an existing project or create one.</p>}
              {projects.data && projects.data.length > 0 && (
                <label className="field">
                  Continue setting up an existing project
                  <select
                    aria-label="Continue setting up an existing project"
                    className="select"
                    disabled={busy}
                    value=""
                    onChange={(event) => {
                      setProject(event.target.value);
                      move("github", event.target.value);
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
              <form
                style={{ display: "flex", flexDirection: "column", gap: 16 }}
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!busy && !duplicateKey && workspace && projects.isSuccess) void create();
                }}
              >
                <label className="field">
                  Project name
                  <input
                    className="input"
                    disabled={busy}
                    value={name}
                    maxLength={100}
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
                    className="input"
                    disabled={busy}
                    value={key}
                    maxLength={10}
                    onChange={(event) => {
                      setKeyEdited(true);
                      setKey(event.target.value.toUpperCase());
                    }}
                    placeholder="APP"
                  />
                </label>
                {duplicateKey && (
                  <p role="alert">A project with this key is already saved. Continue setting up the existing project above, or choose a different key.</p>
                )}
                <label className="field">
                  Description (optional)
                  <textarea className="textarea" disabled={busy} value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} />
                </label>
                <label className="field">
                  Project access
                  <select
                    aria-label="Project access"
                    disabled={busy}
                    className="select"
                    value={accessLevel}
                    onChange={(event) => setAccessLevel(event.target.value as "workspace" | "restricted")}
                  >
                    <option value="workspace">Workspace members</option>
                    <option value="restricted">Only owners, admins and people added</option>
                  </select>
                </label>
                <button
                  className="btn btn-primary"
                  disabled={busy || !workspace || !projects.isSuccess || duplicateKey || !name.trim() || !/^[A-Z][A-Z0-9]{1,9}$/.test(key)}
                  type="submit"
                >
                  {busy ? "Creating project…" : "Create project"}
                </button>
              </form>
            </>
          )}
          {projects.isError && (
            <p role="alert">
              {errorMessage(projects.error)}
              <button onClick={() => void projects.refetch()}>Try again</button>
            </p>
          )}
        </>
      )}
      {current === "github" && (
        <>
          <h1>Connect GitHub</h1>
          <p className="sub">Connect a repository to {project?.name}. GitHub sign-in and repository access are separate connections.</p>
          {github.isLoading && <p role="status">Checking GitHub…</p>}
          {github.isError && (
            <p role="alert">
              {errorMessage(github.error)}
              <button onClick={() => void github.refetch()}>Try again</button>
            </p>
          )}
          {github.data && !github.data.configured && (
            <p>The GitHub App is not available on this server yet. You can start with documents and connect a repository later.</p>
          )}
          {github.data?.install_url && (
            <button
              className="btn btn-secondary"
              disabled={busy}
              onClick={() => {
                move("github");
                installGitHub(github.data as Schemas["GitHubStatus"], workspaceId, location.pathname + location.search);
              }}
            >
              <Ic n="github" s={16} />
              Connect GitHub App
            </button>
          )}
          {repos.isError && (
            <p role="alert">
              {errorMessage(repos.error)}
              <button onClick={() => void repos.refetch()}>Try again</button>
            </p>
          )}
          {!!repos.data?.length && (
            <>
              <label className="field">
                Repository
                <select aria-label="Repository" className="select" value={repoId} onChange={(event) => setRepo(event.target.value)}>
                  <option value="">Select a repository</option>
                  {repos.data.map((repo) => (
                    <option key={`${repo.installation_ref}:${repo.github_repo_id}`} value={`${repo.installation_ref}:${repo.github_repo_id}`}>
                      {repo.full_name}
                    </option>
                  ))}
                </select>
              </label>
              <button className="btn btn-primary" disabled={busy || !repoId} onClick={() => void connectRepo()}>
                Use repository
              </button>
            </>
          )}
          {project?.repo_url && <p>Connected: {project.repo_url}</p>}
          <button className="btn btn-secondary" disabled={busy} onClick={() => move("model")}>
            {project?.repo_url ? "Continue" : "Continue with documents only"}
          </button>
        </>
      )}
      {current === "model" && (
        <>
          <h1>Connect your model</h1>
          <p className="sub">Your personal API key powers Nova and Kai. It is stored encrypted and used for your runs.</p>
          {models.isError && (
            <p role="alert">
              {errorMessage(models.error)}
              <button onClick={() => void models.refetch()}>Try again</button>
            </p>
          )}
          {access.data?.ready && <p role="status">A personal model connection is available.</p>}
          {access.data && !access.data.can_store_keys && <p role="alert">Encrypted key storage is unavailable. Ask your administrator to configure it.</p>}
          <label className="field">
            Model provider
            <select
              aria-label="Model provider"
              disabled={busy || !models.data}
              className="select"
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
            <input
              className="input"
              type="password"
              value={apiKey}
              autoComplete="off"
              maxLength={400}
              spellCheck={false}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </label>
          <button className="btn btn-primary" disabled={busy || !access.data?.can_store_keys || apiKey.trim().length < 20} onClick={() => void saveKey()}>
            {busy ? "Saving…" : "Save personal key"}
          </button>
          {!!access.data?.models.length && (
            <label className="field">
              Default model
              <select
                aria-label="Default model"
                disabled={busy}
                className="select"
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
          {access.isError && (
            <p role="alert">
              {errorMessage(access.error)}
              <button onClick={() => void access.refetch()}>Try again</button>
            </p>
          )}
          <button className="btn btn-secondary" disabled={busy || (!!access.data?.ready && !modelReady)} onClick={() => move("ready")}>
            {access.data?.ready ? "Continue" : "Set up models later"}
          </button>
        </>
      )}
      {current === "ready" && (
        <>
          <h1>Your project is ready</h1>
          <p>
            {project?.name} is saved in {workspace?.name}.
          </p>
          <p>{project?.repo_url ? "GitHub repository connected." : "Documents-only project; GitHub can be connected later."}</p>
          <p>{access.data?.ready ? "Personal model connection available." : "Connect a model when you are ready to use agents."}</p>
          <a className="btn btn-primary" href={`/w/${workspace?.slug}/p/${project?.key}/overview`}>
            Open project
          </a>
          {modelReady ? (
            <a className="btn btn-secondary" href={`/w/${workspace?.slug}/chat?project=${project?.key}`}>
              Start with Nova
            </a>
          ) : (
            <button className="btn btn-secondary" disabled={busy} onClick={() => move("model")}>
              Set up Nova
            </button>
          )}
        </>
      )}
      {current !== "project" && (
        <button className="btn btn-ghost" disabled={busy} onClick={() => move(steps[Math.max(0, steps.indexOf(current) - 1)]!)}>
          Back
        </button>
      )}
      {workspace && (
        <a className="btn btn-ghost" href={`/w/${workspace.slug}`}>
          {project ? "Finish setup later" : "Back to workspace"}
        </a>
      )}
      {error && (
        <p className="err" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
