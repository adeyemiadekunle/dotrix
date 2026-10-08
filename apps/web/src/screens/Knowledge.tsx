// dotrix's Knowledge tab in Gr8r's design: the project's documents (.pmagent/), by folder; read one
// (Markdown), edit it with a note, see who wrote it (a person or an agent). Agents' edits arrive
// as changes to approve in Chat and Notifications.
import { useState } from "react";

import { Ic } from "../core/icons";
import { go } from "../core/nav";
import { ago, uid } from "../core/utils";
import { D, S, mutate, render, who } from "../data/store";
import type { KnowledgeFile, Project } from "../data/types";
import { Markdown } from "@/components/markdown";
import { Av, Empty } from "../ui/helpers";
import { toast } from "../ui/toast";

const open: { path: string | null; editing: boolean; q: string } = { path: null, editing: false, q: "" };

function tree(files: KnowledgeFile[]) {
  const root: { dirs: Record<string, KnowledgeFile[]>; files: KnowledgeFile[] } = { dirs: {}, files: [] };
  for (const f of files) {
    const [dir, ...rest] = f.path.split("/");
    if (rest.length) (root.dirs[dir!] ||= []).push(f);
    else root.files.push(f);
  }
  return root;
}

export function Knowledge({ p }: { p: Project }) {
  const files = D()
    .knowledge.filter((f) => f.project === p.id)
    .filter((f) => !open.q || f.path.toLowerCase().includes(open.q.toLowerCase()));
  const t = tree(files);
  const cur = D().knowledge.find((f) => f.project === p.id && f.path === (open.path ?? "project.md")) ?? files[0];
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const pick = (f: KnowledgeFile) => {
    open.path = f.path;
    open.editing = false;
    render();
  };
  const save = () => {
    if (!cur) return;
    mutate(() => {
      cur.content = draft;
      cur.version += 1;
      cur.by = D().me;
      cur.at = Date.now();
      D().activity.unshift({ id: uid("a"), by: D().me, verb: "updated", task: null, project: p.id, at: Date.now(), extra: cur.path + (note ? ` — ${note}` : "") });
    });
    open.editing = false;
    setNote("");
    render();
    toast(`Saved ${cur.path} (v${cur.version})`);
  };
  const Item = ({ f, indent }: { f: KnowledgeFile; indent?: boolean }) => (
    <button className={`sitem ${cur?.path === f.path ? "on" : ""}`} style={indent ? { paddingLeft: 26 } : undefined} onClick={() => pick(f)}>
      <Ic n="file-text" s={14} />
      <span className="trunc">{f.path.split("/").pop()}</span>
    </button>
  );
  return (
    <div className="page wide" style={{ paddingTop: 16 }}>
      {!D().knowledge.some((f) => f.project === p.id) ? (
        <Empty icon="book-open" title="No documents yet" text="The project's requirements, decisions, and research live here, kept current by the agents. Upload documents in Files, or ask in Chat." />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "240px minmax(0,1fr)", gap: 16, alignItems: "start" }} className="kn-grid">
          <aside className="panel" style={{ padding: 6 }}>
            <div className="inwrap" style={{ margin: "2px 2px 6px" }}>
              <Ic n="search" s={13} />
              <input className="input search-sm" style={{ width: "100%" }} placeholder="Find a document" value={open.q} onChange={(e) => ((open.q = e.target.value), render())} aria-label="Find a document" />
            </div>
            {t.files.map((f) => (
              <Item key={f.path} f={f} />
            ))}
            {Object.entries(t.dirs).map(([dir, list]) => (
              <div key={dir}>
                <div className="sitem" style={{ cursor: "default", color: "var(--text-3)" }}>
                  <Ic n="folder" s={14} />
                  <span>{dir}</span>
                  <span className="ct">{list.length}</span>
                </div>
                {list.map((f) => (
                  <Item key={f.path} f={f} indent />
                ))}
              </div>
            ))}
          </aside>
          {cur && (
            <section className="panel">
              <div className="panel-h" style={{ borderBottom: "1px solid var(--divider)", paddingBottom: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <h2 className="mono" style={{ fontSize: 13 }}>
                    {cur.path}
                  </h2>
                  <div className="row faint" style={{ gap: 6, fontSize: 12, marginTop: 4 }}>
                    <Av id={cur.by} cls="sm" tip={false} />v{cur.version} · {who(cur.by)?.name} · {ago(cur.at)}
                  </div>
                </div>
                <div className="acts">
                  {open.editing ? (
                    <>
                      <button className="btn btn-sm btn-ghost" onClick={() => ((open.editing = false), render())}>
                        Cancel
                      </button>
                      <button className="btn btn-sm btn-primary" onClick={save} disabled={draft === cur.content}>
                        Save
                      </button>
                    </>
                  ) : (
                    <>
                      <button className="btn btn-sm btn-ghost" onClick={() => go("chat", {}, { search: `project=${p.key}` })}>
                        <Ic n="sparkles" s={13} />
                        Ask an agent to update
                      </button>
                      <button
                        className="btn btn-sm btn-secondary"
                        onClick={() => {
                          setDraft(cur.content);
                          open.editing = true;
                          render();
                        }}
                        disabled={S.ui.offline}
                      >
                        <Ic n="pencil" s={13} />
                        Edit
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div className="panel-b" style={{ paddingTop: 14 }}>
                {open.editing ? (
                  <div className="col" style={{ gap: 10 }}>
                    <textarea className="textarea mono" rows={18} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Document" style={{ fontSize: 12.5 }} />
                    <input className="input" placeholder="What changed? (optional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Change note" />
                  </div>
                ) : (
                  <Markdown>{cur.content}</Markdown>
                )}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
