import { TabList, Tab } from "@dotrix/ui/astryx";
import { Textarea as DesignTextarea } from "@dotrix/ui/components/textarea";
import { Input as DesignInput } from "@dotrix/ui/components/input";
import { ActionButton } from "@dotrix/ui/components/action-button";
// dotrix's Knowledge tab: the project's documents (.dotrix/), by folder; read one
// (Markdown), edit it with a note, see who wrote it (a person or an agent). Agents' edits arrive
// as changes to approve in Chat and the Inbox.
import { useId, useState } from "react";
import { useGraphNeighbors } from "@/lib/graph";
import { openTask } from "../core/actions";

import { Ic } from "../core/icons";
import { go } from "../core/nav";
import { ago, uid } from "../core/utils";
import { isLive, knowledgeSaved, live } from "../data/live";
import { useLiveKnowledgeFile, useLiveKnowledgeFiles } from "../../lib/workspace-data";
import { D, S, mutate, render, who } from "../data/store";
import { useProjectFiles } from "../data/lists";
import type { KnowledgeFile, Project } from "../data/types";
import { Markdown } from "@/components/markdown";
import { Coverage } from "../views/Coverage";
import { Files } from "../views/Files";
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

/** Open one of a project's documents in Knowledge (a chat reply's file chip). */
export function openDocument(p: Project, path: string) {
  open.path = path;
  open.editing = false;
  go("project", { id: p.key, tab: "knowledge" });
}

function relationshipLabel(kind: string, direction: "in" | "out") {
  const labels: Record<string, [string, string]> = {
    supersedes: ["Supersedes", "Superseded by"],
    implements: ["Implements", "Implemented by"],
    decided_by: ["Decided by", "Guides"],
    affects: ["Affects", "Affected by"],
  };
  return labels[kind]?.[direction === "out" ? 0 : 1] ?? "Related";
}

export function Knowledge({ p, view = "docs" }: { p: Project; view?: "docs" | "files" | "coverage" }) {
  const scope = live.ws && isLive() ? { workspaceId: live.ws.id, projectId: p.id } : undefined;
  const liveFiles = useLiveKnowledgeFiles(scope);
  const files = isLive()
    ? (liveFiles ?? [])
    : D()
        .knowledge.filter((f) => f.project === p.id)
        .filter((f) => !open.q || f.path.toLowerCase().includes(open.q.toLowerCase()));
  const folderId = useId();
  const [browsing, setBrowsing] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const t = tree(files.filter((f) => !open.q || f.path.toLowerCase().includes(open.q.toLowerCase())));
  const curEntry = files.find((f) => f.path === (open.path ?? "project.md")) ?? files[0];
  const liveCur = useLiveKnowledgeFile(scope, curEntry?.path);
  const cur = isLive() ? (liveCur ?? curEntry) : curEntry;
  const relationships = useGraphNeighbors(view === "docs" && !cur?.path.startsWith("agent-rules/") ? scope : undefined, cur?.path);
  const visibleLinks = (relationships.data?.links ?? []).filter(
    (link, _, links) =>
      link.node.kind !== "module" && !(link.kind === "mentions" && links.some((other) => other.node.ref === link.node.ref && other.kind !== "mentions")),
  );
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const pick = (f: KnowledgeFile) => {
    setBrowsing(false);
    open.path = f.path;
    open.editing = false;
    render();
  };
  const save = () => {
    if (!cur) return;
    if (isLive()) {
      knowledgeSaved(cur, draft, note);
      open.editing = false;
      setNote("");
      render();
      return;
    }
    mutate(() => {
      cur.content = draft;
      cur.version += 1;
      cur.by = D().me;
      cur.at = Date.now();
      D().activity.unshift({
        id: uid("a"),
        by: D().me,
        verb: "updated",
        task: null,
        project: p.id,
        at: Date.now(),
        extra: cur.path + (note ? ` — ${note}` : ""),
      });
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
  // The uploaded originals sit beside the documents made from them.
  const nFiles = useProjectFiles(p.id).items.length;
  const seg = (
    <TabList
      aria-label="Knowledge"
      value={view}
      onChange={(value) => go("project", { id: p.key, tab: "knowledge" }, { replace: true, search: value === "docs" ? undefined : `view=${value}` })}
      size="sm"
    >
      <Tab value="docs" label="Documents" />
      <Tab value="files" label={nFiles ? `Files ${nFiles}` : "Files"} />
      {isLive() && <Tab value="coverage" label="Coverage" />}
    </TabList>
  );
  if (view === "files") return <Files pid={p.id} lead={seg} />;
  if (view === "coverage" && isLive()) return <Coverage pid={p.id} lead={seg} openPage={(path) => openDocument(p, path)} />;
  return (
    <>
      <div className="toolbar">{seg}</div>
      <div className="page knowledge-documents">
        {!files.length ? (
          <Empty
            icon="book-open"
            title="No documents yet"
            text="The project's requirements, decisions, and research live here, kept current by the agents. Upload documents under Files, or ask in Chat."
          />
        ) : (
          <div className={`kn-grid grid min-w-0 items-start gap-4 sm:grid-cols-[240px_minmax(0,1fr)] ${browsing ? "browsing" : ""}`}>
            <div className="kn-mobile-nav rounded-lg border border-border bg-surface p-3 text-primary">
              <ActionButton
                className="btn btn-secondary"
                onClick={() => setBrowsing(!browsing)}
                aria-expanded={browsing}
                aria-controls={`${folderId}-documents`}
              >
                <Ic n={browsing ? "arrow-left" : "folder"} s={16} />
                {browsing ? "Back to document" : "Documents"}
              </ActionButton>
            </div>
            <aside id={`${folderId}-documents`} className="panel" style={{ padding: 6 }}>
              <div className="inwrap" style={{ margin: "2px 2px 6px" }}>
                <Ic n="search" s={13} />
                <DesignInput
                  className="input search-sm"
                  style={{ width: "100%" }}
                  placeholder="Find a document"
                  value={open.q}
                  onChange={(e) => ((open.q = e.target.value), render())}
                  aria-label="Find a document"
                />
              </div>
              {t.files.map((f) => (
                <Item key={f.path} f={f} />
              ))}
              {Object.entries(t.dirs).map(([dir, list]) => {
                const key = `${p.id}/${dir}`;
                const expanded = !collapsed[key];
                const id = `${folderId}-${encodeURIComponent(dir)}`;
                return (
                  <div key={dir}>
                    <button
                      type="button"
                      className="sitem"
                      aria-expanded={expanded}
                      aria-controls={id}
                      onClick={() => setCollapsed((current) => ({ ...current, [key]: expanded }))}
                    >
                      <Ic n={expanded ? "chevron-down" : "chevron-right"} s={12} />
                      <Ic n={expanded ? "folder-open" : "folder"} s={14} />
                      <span className="trunc">{dir}</span>
                      <span className="ct">{list.length}</span>
                    </button>
                    <div id={id} hidden={!expanded}>
                      {list.map((f) => (
                        <Item key={f.path} f={f} indent />
                      ))}
                    </div>
                  </div>
                );
              })}
            </aside>
            {cur && (
              <section className="panel">
                <div className="panel-h" style={{ borderBottom: "1px solid var(--divider)", paddingBottom: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <h2 className="mono" style={{ fontSize: 13 }}>
                      {cur.path}
                    </h2>
                    <div className="row faint" style={{ gap: 6, fontSize: 12, marginTop: 4 }}>
                      {cur.by && <Av id={cur.by} cls="sm" tip={false} />}v{cur.version}
                      {cur.by && ` · ${who(cur.by)?.name}`} · {ago(cur.at)}
                    </div>
                  </div>
                  <div className="acts">
                    {open.editing ? (
                      <>
                        <ActionButton className="btn btn-sm btn-ghost" onClick={() => ((open.editing = false), render())}>
                          Cancel
                        </ActionButton>
                        <ActionButton className="btn btn-sm btn-primary" onClick={save} disabled={draft === cur.content}>
                          Save
                        </ActionButton>
                      </>
                    ) : (
                      <>
                        <ActionButton className="btn btn-sm btn-ghost" onClick={() => go("chat", {}, { search: `project=${p.key}` })}>
                          <Ic n="sparkles" s={13} />
                          Ask an agent to update
                        </ActionButton>
                        <ActionButton
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
                        </ActionButton>
                      </>
                    )}
                  </div>
                </div>
                <div className="panel-b" style={{ paddingTop: 14 }}>
                  {!!visibleLinks.length && (
                    <section aria-label="Shared document relationships" style={{ marginBottom: 14 }}>
                      <b>Related project work</b>
                      <div className="col" style={{ gap: 6, marginTop: 6 }}>
                        {visibleLinks.map((link) => (
                          <ActionButton
                            key={link.id}
                            className="btn btn-sm btn-ghost"
                            style={{ justifyContent: "flex-start" }}
                            onClick={() => {
                              if (link.node.kind === "issue") openTask(link.node.ref);
                              else {
                                openDocument(p, link.node.ref);
                                render();
                              }
                            }}
                          >
                            {relationshipLabel(link.kind, link.direction)} · {link.node.ref} · {link.node.title}
                          </ActionButton>
                        ))}
                      </div>
                    </section>
                  )}
                  {open.editing ? (
                    <div className="col" style={{ gap: 10 }}>
                      <DesignTextarea
                        className="textarea mono"
                        rows={18}
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        aria-label="Document"
                        style={{ fontSize: 12.5 }}
                      />
                      <DesignInput
                        className="input"
                        placeholder="What changed? (optional)"
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        aria-label="Change note"
                      />
                    </div>
                  ) : (
                    <Markdown outline>{cur.content}</Markdown>
                  )}
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </>
  );
}
