// Gr8r's search results (gr8r-studio/src/pages/search.js). dotrix adds the projects' documents.
import type { CSSProperties, ReactNode } from "react";

import { openTask } from "../core/actions";
import { Ic } from "../core/icons";
import { go } from "../core/nav";
import { ago } from "../core/utils";
import { D, S, allTasks, canSee, mem, pColor, proj, render, task, visibleProjects } from "../data/store";
import { Av, Empty, FT, Hl, PIcon, PStatus, StIcon } from "../ui/helpers";

export function searchAll(raw: string) {
  const q = (raw || "").trim().toLowerCase();
  if (!q) return { tasks: [], projects: [], people: [], files: [], documents: [], comments: [] };
  const has = (s?: string | null) => (s || "").toLowerCase().includes(q);
  return {
    tasks: allTasks()
      .filter((t) => has(t.title) || has(t.key) || has(t.desc.replace(/<[^>]+>/g, "")))
      .slice(0, 30),
    projects: visibleProjects().filter((p) => has(p.name) || has(p.desc)),
    people: D().members.filter((m) => has(m.name) || has(m.email) || has(m.title)),
    files: D().files.filter((f) => has(f.name) && canSee(proj(f.project))),
    documents: D().knowledge.filter((f) => (has(f.path) || has(f.content)) && canSee(proj(f.project))),
    comments: D().comments.filter((c) => has(c.text) && task(c.task) && canSee(proj(task(c.task)!.project))),
  };
}

const setSearch = (q: string) => ((S.ui.searchQ = q), render());

export function Search() {
  const q = S.ui.searchQ;
  const r = searchAll(q);
  const cat = S.ui.searchCat;
  const cats: [keyof typeof r | "all", string][] = [
    ["all", "All"],
    ["tasks", "Tasks"],
    ["projects", "Projects"],
    ["people", "People"],
    ["files", "Files"],
    ["documents", "Documents"],
    ["comments", "Comments"],
  ];
  const total = Object.values(r).reduce((a, b) => a + b.length, 0);
  const sec = (k: keyof typeof r, title: string, rows: ReactNode) =>
    (cat === "all" || cat === k) && r[k].length ? (
      <section key={k} style={{ marginBottom: 22 }}>
        <div className="eyebrow" style={{ marginBottom: 6 }}>
          {title} · {r[k].length}
        </div>
        <div className="panel" style={{ overflow: "hidden" }}>
          {rows}
        </div>
      </section>
    ) : null;
  return (
    <div className="page" style={{ maxWidth: 860 }}>
      <div className="inwrap" style={{ marginBottom: 14 }}>
        <Ic n="search" s={16} />
        <input
          className="input input-lg"
          id="search-page-q"
          placeholder="Search tasks, projects, people, files, documents, and comments"
          value={q}
          onChange={(e) => setSearch(e.target.value)}
          style={{ paddingLeft: 34, fontSize: 15 }}
          aria-label="Search"
          autoFocus
        />
      </div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {cats.map(([k, n]) => (
          <button key={k} className={`tab ${cat === k ? "on" : ""}`} onClick={() => ((S.ui.searchCat = k), render())}>
            {n}
            <span className="cnt">{k === "all" ? total : r[k].length}</span>
          </button>
        ))}
      </div>
      {!q ? (
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          <span className="faint" style={{ fontSize: 12.5 }}>
            Recent:
          </span>
          {D().recentSearches.map((s) => (
            <button key={s} className="badge" onClick={() => setSearch(s)}>
              <Ic n="history" s={11} />
              {s}
            </button>
          ))}
        </div>
      ) : total ? (
        <>
          {sec(
            "tasks",
            "Tasks",
            r.tasks.map((t) => (
              <div key={t.id} className="mini" onClick={() => openTask(t.id)}>
                <StIcon st={t.status} />
                <span className="mono faint" style={{ fontSize: 11 }}>
                  {t.key}
                </span>
                <span className="tt">
                  <Hl text={t.title} q={q} />
                </span>
                <span className="pj">
                  <span className="pdot" style={{ "--c": pColor(proj(t.project)) } as CSSProperties} />
                  {proj(t.project)?.name}
                </span>
                <Av id={t.assignee} cls="sm" />
              </div>
            )),
          )}
          {sec(
            "projects",
            "Projects",
            r.projects.map((p) => (
              <div key={p.id} className="mini" onClick={() => go("project", { id: p.key })}>
                <PIcon p={p} s={13} />
                <span className="tt">
                  <Hl text={p.name} q={q} />{" "}
                  <span className="faint" style={{ fontSize: 12 }}>
                    — {p.desc.slice(0, 70)}…
                  </span>
                </span>
                <PStatus s={p.status} />
              </div>
            )),
          )}
          {sec(
            "people",
            "People",
            r.people.map((m) => (
              <div key={m.id} className="mini" onClick={() => go("member", { id: m.id })}>
                <Av id={m.id} cls="md" tip={false} />
                <span className="tt">
                  <Hl text={m.name} q={q} />{" "}
                  <span className="faint" style={{ fontSize: 12 }}>
                    {m.title}
                  </span>
                </span>
                <span className="faint" style={{ fontSize: 12 }}>
                  {m.email}
                </span>
              </div>
            )),
          )}
          {sec(
            "files",
            "Files",
            r.files.map((f) => (
              <div key={f.id} className="mini" onClick={() => go("project", { id: proj(f.project)!.key, tab: "files" })}>
                <span className="ftype" style={{ "--c": (FT[f.type] || FT.other!).c } as CSSProperties}>
                  <Ic n={(FT[f.type] || FT.other!).i} s={14} />
                </span>
                <span className="tt">
                  <Hl text={f.name} q={q} />
                </span>
                <span className="faint" style={{ fontSize: 12 }}>
                  {f.size} · {proj(f.project)?.name}
                </span>
              </div>
            )),
          )}
          {sec(
            "documents",
            "Documents",
            r.documents.map((f) => (
              <div key={f.project + f.path} className="mini" onClick={() => go("project", { id: proj(f.project)!.key, tab: "knowledge" })}>
                <Ic n="book-open" s={14} />
                <span className="tt mono" style={{ fontSize: 12.5 }}>
                  <Hl text={f.path} q={q} />
                </span>
                <span className="faint" style={{ fontSize: 12 }}>
                  {proj(f.project)?.name}
                </span>
              </div>
            )),
          )}
          {sec(
            "comments",
            "Comments",
            r.comments.map((c) => (
              <div key={c.id} className="mini" style={{ alignItems: "flex-start", paddingTop: 10, paddingBottom: 10 }} onClick={() => openTask(c.task)}>
                <Av id={c.by} cls="sm" />
                <div className="grow" style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12 }} className="muted">
                    <b style={{ color: "var(--text)", fontWeight: 500 }}>{mem(c.by)?.name}</b> on {task(c.task)?.title} · {ago(c.at)}
                  </div>
                  <div style={{ fontSize: 13 }}>
                    <Hl text={c.text} q={q} />
                  </div>
                </div>
              </div>
            )),
          )}
        </>
      ) : (
        <div className="panel">
          <Empty icon="search-x" title="No results found" text={`Nothing matches “${q}”. Check the spelling or try a broader term.`}>
            <button className="btn btn-secondary btn-sm" onClick={() => setSearch("")}>
              Clear search
            </button>
          </Empty>
        </div>
      )}
    </div>
  );
}
