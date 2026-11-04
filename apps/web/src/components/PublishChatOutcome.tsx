import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api";
import { useAllIssues, type Scope } from "@/lib/issues";
import { useKnowledge, useKnowledgeFile } from "@/lib/knowledge";
import { allowed } from "../core/can";
import { openTask } from "../core/actions";
import { live } from "../data/live";
import { proj } from "../data/store";
import { openDocument } from "../screens/Knowledge";
import { Markdown } from "@/components/markdown";

type Draft = Schemas["ChatPublicationCreate"];
type Published = Schemas["ChatPublicationRead"];
const destinations = ["requirements", "decisions", "research", "task"] as const;

/** Only mounted for an owner's completed live project reply, never for sample sessions. */
export function PublishChatOutcome({ scope, runId, reply }: { scope: Scope; runId: string; reply: string }) {
  const client = useQueryClient();
  const key = ["chat-publications", scope.workspaceId, scope.projectId, runId];
  const path = { workspace_id: scope.workspaceId, project_id: scope.projectId, run_id: runId };
  const saved = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/publications", { params: { path } })),
  });
  const canWriteDocs = allowed("knowledge:write");
  const canWriteTasks = !!live.ws?.permissions?.includes("issues:write");
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [destination, setDestination] = useState<Draft["destination"]>(canWriteDocs ? "requirements" : "task");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState(reply);
  const [relatedPath, setRelatedPath] = useState("");
  const [supersedesPath, setSupersedesPath] = useState("");
  const [relatedIssue, setRelatedIssue] = useState("");
  const files = useKnowledge(open ? scope : undefined);
  const issues = useAllIssues(open ? scope : undefined);
  const document = useKnowledgeFile(open ? scope : undefined, relatedPath || undefined);
  const predecessor = useKnowledgeFile(open ? scope : undefined, supersedesPath || undefined);
  // Freeze exactly what the person sees. Background refreshes must never silently
  // admit a new version while the confirmation preview is open.
  const [reviewed, setReviewed] = useState<{ document?: Schemas["FileRead"]; predecessor?: Schemas["FileRead"] }>({});
  const sharedFiles = (files.data?.files ?? []).filter(
    (file) => !file.deleted && /^(requirements|decisions|research)\/[\w./-]+\.md$/.test(file.path) && !file.path.includes(".."),
  );
  const ref = (file: Schemas["FileRead"] | undefined) => (file ? { path: file.path, version: file.version } : null);
  const relationships = [
    reviewed.predecessor ? `Supersedes: /dotrix/${reviewed.predecessor.path} (reviewed version ${reviewed.predecessor.version})` : "",
    reviewed.document ? `Shared context: /dotrix/${reviewed.document.path} (reviewed version ${reviewed.document.version})` : "",
    relatedIssue ? `Related task: ${relatedIssue}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
  const attempt = useRef<{ signature: string; body: Draft } | null>(null);
  const save = useMutation({
    mutationFn: (body: Draft) =>
      unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/publications", { params: { path }, body })),
    onSuccess: (result) => {
      client.setQueryData<Published[]>(key, (old = []) => [...old.filter((item) => item.target !== result.target), result]);
      void client.invalidateQueries({ queryKey: ["knowledge", scope.projectId] });
      void client.invalidateQueries({ queryKey: ["issues"] });
      void client.invalidateQueries({ queryKey: ["activity"] });
      void client.invalidateQueries({ queryKey: ["graph", scope.projectId] });
      setOpen(false);
    },
  });
  const publish = () => {
    if (!acknowledged || save.isPending) return;
    const fields = {
      destination,
      title,
      content,
      acknowledge_shared: true as const,
      related_document: ref(reviewed.document),
      supersedes: ref(reviewed.predecessor),
      related_issue: relatedIssue || null,
    };
    const signature = JSON.stringify(fields);
    if (attempt.current?.signature !== signature) attempt.current = { signature, body: { ...fields, request_id: crypto.randomUUID() } };
    save.mutate(attempt.current.body);
  };
  const openShared = (item: Published) => {
    if (item.destination === "task") openTask(item.target);
    else {
      const project = proj(scope.projectId);
      if (project) openDocument(project, item.target);
    }
  };
  return (
    <section aria-label="Shared chat outcomes" style={{ marginTop: 12 }}>
      {saved.data?.map((item) => (
        <button key={item.target} className="btn btn-sm btn-ghost" onClick={() => openShared(item)}>
          Open shared {item.destination === "task" ? `task ${item.target}` : item.destination}
        </button>
      ))}
      {!open && (canWriteDocs || canWriteTasks) && (
        <div className="chat-share-action">
          <button
            className="btn btn-sm btn-secondary"
            onClick={() => {
              setOpen(true);
              setPreview(false);
              setAcknowledged(false);
              save.reset();
            }}
          >
            Publish outcome to project
          </button>
          <span className="faint">Create a project document or task from this reply.</span>
        </div>
      )}
      {open && (
        <section className="panel" aria-label="Publish selected outcome">
          <div className="panel-b">
            <p>Share an agreed outcome with people who can access this project. Only the content below is published; your conversation stays private.</p>
            {!preview ? (
              <>
                <label className="field">
                  Destination
                  <select
                    aria-label="Destination"
                    className="input"
                    value={destination}
                    onChange={(e) => {
                      setDestination(e.target.value as Draft["destination"]);
                      setSupersedesPath("");
                    }}
                  >
                    {destinations
                      .filter((d) => (d === "task" ? canWriteTasks : canWriteDocs))
                      .map((d) => (
                        <option key={d} value={d}>
                          {d === "task" ? "Task" : d[0].toUpperCase() + d.slice(1)}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="field">
                  Outcome title
                  <input className="input" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
                </label>
                <label className="field">
                  Selected content
                  <textarea
                    aria-label="Selected content"
                    className="textarea"
                    rows={10}
                    maxLength={100000}
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                  />
                </label>
                <label className="field">
                  Link shared document (optional)
                  <select aria-label="Link shared document" className="input" value={relatedPath} onChange={(e) => setRelatedPath(e.target.value)}>
                    <option value="">No document link</option>
                    {sharedFiles.map((file) => (
                      <option key={file.path} value={file.path}>
                        {file.path}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Link existing task (optional)
                  <select aria-label="Link existing task" className="input" value={relatedIssue} onChange={(e) => setRelatedIssue(e.target.value)}>
                    <option value="">No task link</option>
                    {(issues.data ?? []).map((issue) => (
                      <option key={issue.key} value={issue.key}>
                        {issue.key} — {issue.title}
                      </option>
                    ))}
                  </select>
                </label>
                {destination === "decisions" && (
                  <label className="field">
                    Supersede decision (optional)
                    <select aria-label="Supersede decision" className="input" value={supersedesPath} onChange={(e) => setSupersedesPath(e.target.value)}>
                      <option value="">A separate new decision</option>
                      {sharedFiles
                        .filter((file) => file.path.startsWith("decisions/"))
                        .map((file) => (
                          <option key={file.path} value={file.path}>
                            {file.path}
                          </option>
                        ))}
                    </select>
                  </label>
                )}
                {(document.isError || predecessor.isError || files.isError || issues.isError) && (
                  <p role="alert">Could not load shared context. Reload it before selecting a link.</p>
                )}
                <p className="faint">
                  Remove private details, secrets and transcript links. Include the agreed scope, rationale and any open questions a teammate needs.
                </p>
                <button
                  className="btn btn-sm btn-primary"
                  disabled={
                    !title.trim() ||
                    !content.trim() ||
                    (!!relatedPath && (!document.data || document.isFetching || document.isError)) ||
                    (!!supersedesPath && (!predecessor.data || predecessor.isFetching || predecessor.isError))
                  }
                  onClick={() => {
                    setReviewed({ document: relatedPath ? document.data : undefined, predecessor: supersedesPath ? predecessor.data : undefined });
                    setPreview(true);
                    setAcknowledged(false);
                    save.reset();
                  }}
                >
                  Preview publication
                </button>
              </>
            ) : (
              <>
                <p>
                  <b>Destination:</b> {destination === "task" ? "A new unassigned task, To do" : `A new document in ${destination}/`}. Existing documents are
                  preserved.
                </p>
                <p>
                  <b>Visibility:</b> People with access to this project.
                </p>
                <div aria-label="Publication preview">
                  <h3>{title}</h3>
                  <Markdown>{content.trim() + (relationships ? `\n\n${relationships}` : "")}</Markdown>
                </div>
                {[reviewed.document, reviewed.predecessor]
                  .filter((file): file is Schemas["FileRead"] => !!file)
                  .map((file, index) => (
                    <details key={`${file.path}-${index}`} open={file === reviewed.predecessor}>
                      <summary>
                        Reviewed shared document: {file.path}, version {file.version}
                      </summary>
                      <Markdown>{file.content}</Markdown>
                    </details>
                  ))}
                {reviewed.predecessor && (
                  <p role="note">
                    The previous decision's text is retained. A new version appends a “Superseded by” link to this new decision. If it changes before
                    publication, you must review it again.
                  </p>
                )}
                <p className="faint">
                  This is a human publication. It does not start coding, approve agent changes, or mark implementation complete. Documents can be corrected
                  later in Knowledge with version history.
                </p>
                <label>
                  <input type="checkbox" checked={acknowledged} disabled={save.isPending} onChange={(e) => setAcknowledged(e.target.checked)} /> I reviewed this
                  content and want to share it with the project.
                </label>
                {save.isError && <p role="alert">{errorMessage(save.error)} Your draft is retained. Retry the same publication safely.</p>}
                <div className="row" style={{ gap: 8, marginTop: 12 }}>
                  <button
                    className="btn btn-sm btn-secondary"
                    disabled={save.isPending}
                    onClick={() => {
                      setPreview(false);
                      setAcknowledged(false);
                      if (relatedPath) void document.refetch();
                      if (supersedesPath) void predecessor.refetch();
                    }}
                  >
                    Edit selection
                  </button>
                  <button className="btn btn-sm btn-primary" disabled={!acknowledged || save.isPending} onClick={publish}>
                    {save.isPending ? "Publishing…" : "Publish to project"}
                  </button>
                </div>
              </>
            )}
            <button className="btn btn-sm btn-ghost" disabled={save.isPending} onClick={() => setOpen(false)}>
              Close
            </button>
          </div>
        </section>
      )}
    </section>
  );
}
