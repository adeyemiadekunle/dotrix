import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api";
import type { Scope } from "@/lib/issues";
import { openTask } from "../core/actions";
import { go } from "../core/nav";

type Preview = Schemas["GitHubImportPreviewRead"];
export function GitHubIssueImport({ scope, projectKey }: { scope: Scope | undefined; projectKey: string }) {
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [state, setState] = useState<"open" | "closed" | "all">("all");
  const [openStatus, setOpenStatus] = useState<"backlog" | "todo">("backlog");
  const [snapshot, setSnapshot] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [ack, setAck] = useState(false);
  const path = scope ? { workspace_id: scope.workspaceId, project_id: scope.projectId } : undefined;
  const preview = useMutation({
    mutationFn: () => {
      if (!path) throw new Error("Sample imports are read-only");
      return unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/issues/preview", {
          params: { path },
          body: { page, state, open_status: openStatus },
        }),
      );
    },
    onSuccess: (data) => {
      setSnapshot(data);
      setSelected([]);
      setAck(false);
      imported.reset();
    },
  });
  const imported = useMutation({
    mutationFn: () => {
      if (!path || !snapshot || !ack) throw new Error("Review a preview before importing");
      return unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/repository/issues/import", {
          params: { path },
          body: { preview_id: snapshot.id, issue_ids: selected, acknowledge_shared: true },
        }),
      );
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["issues"] });
      void client.invalidateQueries({ queryKey: ["activity"] });
    },
  });
  const busy = preview.isPending || imported.isPending;
  const reset = () => {
    setSnapshot(null);
    setSelected([]);
    setAck(false);
    imported.reset();
  };
  return (
    <div className="page wide" style={{ paddingTop: 20 }}>
      <section className="panel" aria-label="GitHub backlog import">
        <div className="panel-h">
          <h2>Import GitHub Issues</h2>
        </div>
        <div className="panel-b">
          <p>Copy selected issues from this project's connected repository. Preview up to 50 GitHub items per page; pull requests are excluded.</p>
          <p className="muted">
            This is a one-time import. Dotrix owns the imported title, description, state, labels and assignee afterward. Later edits on either side do not
            sync. Existing Dotrix tasks are never overwritten.
          </p>
          <p className="faint">
            All imports are Tasks. Comments, attachments, milestones, GitHub Projects, relationships and other issue types are not imported. Unknown or multiple
            assignees remain unassigned. Closing without completion requires manual review.
          </p>
          {!scope ? (
            <p>Sample imports are read-only. Sign in to import into your project.</p>
          ) : (
            <>
              <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
                <label>
                  GitHub state{" "}
                  <select
                    aria-label="GitHub state"
                    className="input"
                    disabled={busy}
                    value={state}
                    onChange={(e) => {
                      setState(e.target.value as typeof state);
                      setPage(1);
                      reset();
                    }}
                  >
                    <option value="all">All</option>
                    <option value="open">Open</option>
                    <option value="closed">Closed</option>
                  </select>
                </label>
                <label>
                  Open issues become{" "}
                  <select
                    aria-label="Open issues become"
                    className="input"
                    disabled={busy}
                    value={openStatus}
                    onChange={(e) => {
                      setOpenStatus(e.target.value as typeof openStatus);
                      reset();
                    }}
                  >
                    <option value="backlog">Backlog</option>
                    <option value="todo">To do</option>
                  </select>
                </label>
                <span>Page {page}</span>
                <button
                  className="btn btn-sm btn-secondary"
                  disabled={busy || page === 1}
                  onClick={() => {
                    setPage(page - 1);
                    reset();
                  }}
                >
                  Previous page
                </button>
                <button
                  className="btn btn-sm btn-secondary"
                  disabled={busy || !snapshot?.has_more}
                  onClick={() => {
                    setPage(page + 1);
                    reset();
                  }}
                >
                  Next page
                </button>
                <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => preview.mutate()}>
                  {preview.isPending ? "Loading…" : "Load preview"}
                </button>
              </div>
              {preview.isError && <p role="alert">{errorMessage(preview.error)}</p>}
              {snapshot && (
                <>
                  <p>
                    <b>{snapshot.repository}</b> → <b>{projectKey}</b>. Visible to people who can access this project. Preview expires{" "}
                    {new Date(snapshot.expires_at).toLocaleTimeString()}.
                  </p>
                  <p className="faint">
                    Closed completed issues become Done only when you confirm. {snapshot.skipped_pull_requests} pull requests excluded from this page.{" "}
                    {snapshot.has_more ? "More GitHub items are available on the next page." : "End of this GitHub listing."}
                  </p>
                  {!snapshot.items.length && <p>No issues on this page.</p>}
                  {snapshot.items.map((item) => (
                    <article key={item.source_id} className="panel" style={{ padding: 12, marginBottom: 8 }}>
                      <label>
                        <input
                          type="checkbox"
                          aria-label={`Select GitHub issue ${item.number}`}
                          disabled={busy || !!imported.data || item.blocked || !!item.existing_key}
                          checked={selected.includes(item.source_id)}
                          onChange={(e) => {
                            setSelected(e.target.checked ? [...selected, item.source_id] : selected.filter((id) => id !== item.source_id));
                            setAck(false);
                          }}
                        />{" "}
                        <b>
                          #{item.number} {item.title}
                        </b>
                      </label>
                      <p className="muted">
                        {item.blocked ? "Excluded" : `Task · ${item.status === "todo" ? "To do" : item.status === "done" ? "Done" : "Backlog"}`} ·{" "}
                        {item.assignee_name || "Unassigned"} · Labels: {item.labels.join(", ") || "none"}
                      </p>
                      {item.github_assignees.length > 0 && <p className="faint">GitHub assignees: {item.github_assignees.join(", ")}</p>}
                      {item.existing_key && <p>Already linked/imported: {item.existing_key}. Will be skipped.</p>}
                      {item.warnings.map((warning) => (
                        <p className="muted" key={warning}>
                          {warning}
                        </p>
                      ))}
                      <details>
                        <summary>Review description and source</summary>
                        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.description || "No description."}</pre>
                        <a href={item.source_url} target="_blank" rel="noreferrer">
                          Open GitHub source
                        </a>
                      </details>
                    </article>
                  ))}
                  <label>
                    <input type="checkbox" checked={ack} disabled={busy || !!imported.data} onChange={(e) => setAck(e.target.checked)} /> I reviewed the
                    selected content and mappings and want to share these tasks with this project.
                  </label>
                  <p>
                    <button className="btn btn-primary" disabled={busy || !selected.length || !ack || !!imported.data} onClick={() => imported.mutate()}>
                      {imported.isPending ? "Importing…" : `Import ${selected.length} selected issues`}
                    </button>
                  </p>
                  {imported.isError && (
                    <p role="alert">
                      {errorMessage(imported.error)} A lost-response retry uses this same preview and selection. Changed source content requires a new preview.
                    </p>
                  )}
                  {imported.data && (
                    <div role="status">
                      <p>
                        Import finished. {imported.data.items.filter((item) => item.outcome === "created").length} created;{" "}
                        {imported.data.items.filter((item) => item.outcome !== "created").length} skipped.
                      </p>
                      {imported.data.items.map((item) => (
                        <button
                          key={item.source_id}
                          className="btn btn-sm btn-ghost"
                          disabled={item.outcome === "deleted_task"}
                          onClick={() => openTask(item.issue_key)}
                        >
                          {item.issue_key} · {item.outcome.replaceAll("_", " ")}
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}
            </>
          )}
          <button className="btn btn-sm btn-ghost" onClick={() => go("project", { id: projectKey, tab: "board" })}>
            Back to board
          </button>
        </div>
      </section>
    </div>
  );
}
