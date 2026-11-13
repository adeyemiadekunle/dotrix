import { Input as DesignInput } from "@dotrix/ui/components/input";
import { ActionButton } from "@dotrix/ui/components/action-button";
import { useRef, useState } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api";

/** Creation is separate from attachment: even a recovered repository needs an explicit selection. */
export function RepositoryCreate({
  workspaceId,
  installations,
  repositories,
  refresh,
  onCreated,
}: {
  workspaceId: string;
  installations: Schemas["InstallationRead"][];
  repositories: Schemas["RepoOption"][];
  refresh: () => Promise<void>;
  onCreated: (repo: Schemas["RepoOption"]) => void;
}) {
  const organisations = installations.filter((item) => item.account_type === "Organization" && !item.suspended);
  const [owner, setOwner] = useState("");
  const [name, setName] = useState("");
  const [privateRepo, setPrivate] = useState(true);
  const [description, setDescription] = useState("");
  const [stage, setStage] = useState<"edit" | "confirm" | "uncertain" | "created">("edit");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sending = useRef(false);
  const installation = organisations.find((item) => item.id === owner);
  const fullName = installation ? `${installation.account_login}/${name.trim()}` : "";
  const existing = repositories.find((repo) => repo.full_name.toLowerCase() === fullName.toLowerCase());
  const create = async () => {
    if (sending.current || stage !== "confirm" || !installation || existing) return;
    sending.current = true;
    setBusy(true);
    setError("");
    try {
      const repo = await unwrap(
        api.POST("/v1/workspaces/{workspace_id}/github/repos", {
          params: { path: { workspace_id: workspaceId } },
          body: { installation_ref: installation.id, name: name.trim(), private: privateRepo, description: description.trim() },
        }),
      );
      setStage("created");
      onCreated(repo);
    } catch (cause) {
      // GitHub may have accepted a request whose response was lost. Never retry it automatically.
      setStage("uncertain");
      setError(errorMessage(cause));
      await refresh().catch(() => undefined);
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };
  return (
    <section aria-label="Create repository">
      <h2>Start a new repository</h2>
      <p>
        For a personal GitHub account,{" "}
        <a href="https://github.com/new" target="_blank" rel="noreferrer">
          create the repository on GitHub
        </a>{" "}
        with a README, grant the GitHub App access, then refresh and select it here. Dotrix can create repositories directly in organisations only.
      </p>
      {!!organisations.length && (
        <>
          <fieldset disabled={busy || stage !== "edit"} style={{ border: 0, padding: 0, margin: 0 }}>
            <legend>Create in a GitHub organisation</legend>
            <label className="field">
              Repository owner
              <select aria-label="Repository owner" className="select" value={owner} onChange={(event) => setOwner(event.target.value)}>
                <option value="">Choose an organisation</option>
                {organisations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.account_login}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Repository name
              <DesignInput aria-label="Repository name" className="input" value={name} maxLength={100} onChange={(event) => setName(event.target.value)} />
            </label>
            <label className="field">
              Repository visibility
              <select
                aria-label="Repository visibility"
                className="select"
                value={privateRepo ? "private" : "public"}
                onChange={(event) => setPrivate(event.target.value === "private")}
              >
                <option value="private">Private</option>
                <option value="public">Public</option>
              </select>
            </label>
            <label className="field">
              Repository description (optional)
              <DesignInput
                aria-label="Repository description (optional)"
                className="input"
                value={description}
                maxLength={350}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
          </fieldset>
          {stage === "edit" && (
            <ActionButton
              className="btn btn-secondary"
              disabled={!installation || !/^[A-Za-z0-9._-]+$/.test(name.trim()) || !!existing}
              onClick={() => setStage("confirm")}
            >
              Review repository
            </ActionButton>
          )}
          {stage === "confirm" && (
            <>
              <p>
                Create <strong>{fullName}</strong> as a <strong>{privateRepo ? "private" : "public"}</strong> repository with a README? Creating it does not
                connect it to this project.
              </p>
              <ActionButton className="btn btn-primary" disabled={busy || !installation || !!existing} onClick={() => void create()}>
                {busy ? "Creating repository…" : "Confirm creation"}
              </ActionButton>
              <ActionButton className="btn btn-ghost" disabled={busy} onClick={() => setStage("edit")}>
                Cancel creation
              </ActionButton>
            </>
          )}
          {stage === "uncertain" && (
            <>
              <p role="alert">
                {error} Creation was not confirmed. Check {fullName} on GitHub and refresh the repository list before trying again. A repository already created
                there is not deleted by leaving setup.
              </p>
              <ActionButton
                className="btn btn-secondary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await refresh();
                    setStage("edit");
                    setError("");
                  } catch (cause) {
                    setError(errorMessage(cause));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Check available repositories
              </ActionButton>
            </>
          )}
          {existing && (
            <p role="status">{existing.full_name} already exists. Select it in the repository list to connect it; no new repository will be created.</p>
          )}
          {stage === "created" && <p role="status">Repository created. Review the selected repository, then choose Use repository to connect it.</p>}
        </>
      )}
    </section>
  );
}
