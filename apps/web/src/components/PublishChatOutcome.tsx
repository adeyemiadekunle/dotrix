import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api";
import type { Scope } from "@/lib/issues";
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
  const attempt = useRef<{ signature: string; body: Draft } | null>(null);
  const save = useMutation({
    mutationFn: (body: Draft) =>
      unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/publications", { params: { path }, body })),
    onSuccess: (result) => {
      client.setQueryData<Published[]>(key, (old = []) => [...old.filter((item) => item.target !== result.target), result]);
      void client.invalidateQueries({ queryKey: ["knowledge", scope.projectId] });
      void client.invalidateQueries({ queryKey: ["issues"] });
      void client.invalidateQueries({ queryKey: ["activity"] });
      setOpen(false);
    },
  });
  const publish = () => {
    if (!acknowledged || save.isPending) return;
    const fields = { destination, title, content, acknowledge_shared: true as const };
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
        <button
          className="btn btn-sm btn-secondary"
          onClick={() => {
            setOpen(true);
            setPreview(false);
            setAcknowledged(false);
            save.reset();
          }}
        >
          Share selected outcome
        </button>
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
                    onChange={(e) => setDestination(e.target.value as Draft["destination"])}
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
                <p className="faint">
                  Remove private details, secrets and transcript links. Include the agreed scope, rationale and any open questions a teammate needs.
                </p>
                <button
                  className="btn btn-sm btn-primary"
                  disabled={!title.trim() || !content.trim()}
                  onClick={() => {
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
                  <Markdown>{content}</Markdown>
                </div>
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
                  <button className="btn btn-sm btn-secondary" disabled={save.isPending} onClick={() => setPreview(false)}>
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
