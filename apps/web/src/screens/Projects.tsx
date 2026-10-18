// Projects. The workspace Overview folded into Home.
import type { CSSProperties } from "react";

import { openPop } from "../core/actions";
import { PSTAT } from "../core/constants";
import { allowed } from "../core/can";
import { Ic } from "../core/icons";
import { newProject } from "../core/more";
import { go } from "../core/nav";
import { ago, fmtDate, minsAgo } from "../core/utils";
import { S, canSee, mem, progressOf, render, tasksOf, visibleProjects } from "../data/store";
import type { Project } from "../data/types";
import { Av, AvStack, Empty, PIcon, PStatus, ProgBar } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const ctx = (p: Project) => (e: React.MouseEvent<HTMLElement>) => {
  e.preventDefault();
  openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id, x: e.clientX, y: e.clientY });
};
const more = (p: Project) => (e: React.MouseEvent<HTMLElement>) => {
  e.stopPropagation();
  openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id });
};

export function ProjectCard({ p }: { p: Project }) {
  const ts = tasksOf(p.id);
  const pr = progressOf(p.id);
  const open = ts.filter((t) => t.status !== "done").length;
  const locked = !canSee(p);
  return (
    <div className="pcard" onClick={() => go("project", { id: p.key })} onContextMenu={ctx(p)} role="link" tabIndex={0} aria-label={p.name}>
      <div className="row">
        <PIcon p={p} />
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}>
            <b className="trunc" style={{ fontWeight: 600, fontSize: 14 }}>
              {p.name}
            </b>
            {p.fav && (
              <span style={{ color: "var(--amber)" }}>
                <Ic n="star" s={12} />
              </span>
            )}
            {p.private && (
              <span className="faint" data-tip="Private project">
                <Ic n="lock" s={12} />
              </span>
            )}
          </div>
        </div>
        <PStatus s={p.status} />
      </div>
      <div className="desc">{p.desc}</div>
      {locked ? (
        <div className="row faint" style={{ fontSize: 12 }}>
          <Ic n="lock" s={12} />
          Restricted — request access to see tasks
        </div>
      ) : (
        <div className="row" style={{ gap: 10 }}>
          <ProgBar v={pr} cls={p.status === "complete" ? "green" : p.status === "risk" ? "red" : ""} />
          <span className="num" style={{ fontSize: 12, fontWeight: 500 }}>
            {pr}%
          </span>
        </div>
      )}
      <div className="foot">
        <span className="row" style={{ gap: 4 }}>
          <Ic n="circle-check" s={12} />
          {locked ? "—" : `${ts.length - open}/${ts.length}`}
        </span>
        <span className="row" style={{ gap: 4 }}>
          <Ic n="calendar" s={12} />
          {fmtDate(p.due)}
        </span>
        <span className="row hide-m" style={{ gap: 4 }}>
          <Ic n="clock" s={12} />
          {ago(minsAgo(p.last))}
        </span>
        <span className="sp" />
        <AvStack ids={p.members} max={3} />
      </div>
      <button
        className="ibtn ibtn-sm more"
        onClick={more(p)}
        aria-label="Project options"
        style={{ background: "var(--surface)", boxShadow: "0 0 0 1px var(--border)" }}
      >
        <Ic n="ellipsis" s={14} />
      </button>
    </div>
  );
}

export function Projects() {
  const u = S.ui;
  const q = u.projQ.toLowerCase();
  const st = u.projStatus;
  const sort = u.projSort;
  const ps = visibleProjects().filter((p) => (st === "all" || p.status === st) && (!q || p.name.toLowerCase().includes(q) || p.desc.toLowerCase().includes(q)));
  const sorter = (
    { recent: (p: Project) => p.last, name: (p: Project) => p.name, due: (p: Project) => p.due, progress: (p: Project) => -progressOf(p.id) } as Record<
      string,
      (p: Project) => string | number
    >
  )[sort]!;
  ps.sort((a, b) => (sorter(a) > sorter(b) ? 1 : -1));
  const view = u.projView;
  const set = (k: "projQ" | "projStatus" | "projSort", v: string) => ((u[k] = v), render());
  let body;
  if (!visibleProjects().length)
    body = (
      <div className="panel">
        <Empty icon="folder-kanban" title="No projects yet" text="Create your first project to start organizing your work.">
          {allowed("projects:manage") && (
            <button className="btn btn-primary btn-sm" onClick={newProject}>
              <Ic n="plus" s={14} />
              Create project
            </button>
          )}
        </Empty>
      </div>
    );
  else if (!ps.length)
    body = (
      <div className="panel">
        <Empty icon="search-x" title="No results found" text="No projects match your search or filters. Try a different term.">
          <button className="btn btn-secondary btn-sm" onClick={() => ((u.projQ = ""), (u.projStatus = "all"), render())}>
            Clear filters
          </button>
        </Empty>
      </div>
    );
  else if (view === "grid")
    body = (
      <div className="pgrid">
        {ps.map((p) => (
          <ProjectCard key={p.id} p={p} />
        ))}
      </div>
    );
  else if (view === "list")
    body = (
      <div className="panel" style={{ overflow: "hidden" }}>
        {ps.map((p) => {
          const pr = progressOf(p.id);
          return (
            <div key={p.id} className="mini" style={{ minHeight: 52, gap: 12 }} onClick={() => go("project", { id: p.key })} onContextMenu={ctx(p)}>
              <PIcon p={p} />
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="row" style={{ gap: 6 }}>
                  <b style={{ fontWeight: 500 }}>{p.name}</b>
                  {p.private && <Ic n="lock" s={12} />}
                </div>
                <div className="trunc faint" style={{ fontSize: 12 }}>
                  {p.desc}
                </div>
              </div>
              <span className="hide-m">
                <PStatus s={p.status} />
              </span>
              <span className="row hide-m" style={{ width: 140 }}>
                <ProgBar v={pr} />
                <span className="num faint" style={{ fontSize: 11.5 }}>
                  {pr}%
                </span>
              </span>
              <span className="num muted hide-m" style={{ width: 70, fontSize: 12 }}>
                {fmtDate(p.due)}
              </span>
              <AvStack ids={p.members} max={3} />
              <button className="ibtn ibtn-sm" onClick={more(p)} aria-label="Options">
                <Ic n="ellipsis" s={14} />
              </button>
            </div>
          );
        })}
      </div>
    );
  else
    body = (
      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="perm-t" style={{ minWidth: 860 }}>
          <thead>
            <tr>
              <th style={{ paddingLeft: 14 }}>Project</th>
              <th style={{ textAlign: "left" }}>Status</th>
              <th style={{ textAlign: "left" }}>Lead</th>
              <th style={{ textAlign: "left", width: "16%" }}>Progress</th>
              <th>Tasks</th>
              <th style={{ textAlign: "left" }}>Start</th>
              <th style={{ textAlign: "left" }}>Due</th>
              <th style={{ textAlign: "left" }}>Last activity</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {ps.map((p) => {
              const pr = progressOf(p.id);
              return (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => go("project", { id: p.key })} onContextMenu={ctx(p)}>
                  <td style={{ paddingLeft: 14 }}>
                    <span className="row">
                      <PIcon p={p} s={14} />
                      <span style={{ fontWeight: 500 }}>{p.name}</span>
                    </span>
                  </td>
                  <td style={{ textAlign: "left" }}>
                    <PStatus s={p.status} />
                  </td>
                  <td style={{ textAlign: "left" }}>
                    <span className="row">
                      <Av id={p.lead} cls="sm" />
                      {mem(p.lead)?.name}
                    </span>
                  </td>
                  <td>
                    <span className="row">
                      <ProgBar v={pr} />
                      <span className="num faint" style={{ fontSize: 11.5 }}>
                        {pr}%
                      </span>
                    </span>
                  </td>
                  <td className="num">{tasksOf(p.id).length}</td>
                  <td style={{ textAlign: "left" }} className="num muted">
                    {fmtDate(p.start)}
                  </td>
                  <td style={{ textAlign: "left" }} className="num muted">
                    {fmtDate(p.due)}
                  </td>
                  <td style={{ textAlign: "left" }} className="muted">
                    {ago(minsAgo(p.last))}
                  </td>
                  <td>
                    <button className="ibtn ibtn-sm" onClick={more(p)} aria-label="Options">
                      <Ic n="ellipsis" s={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  return (
    <div className="page wide">
      <div className="ph">
        <div>
          <h1>Projects</h1>
          <p>
            {visibleProjects().filter((p) => p.status !== "complete").length} active · {visibleProjects().filter((p) => p.status === "complete").length}{" "}
            completed
          </p>
        </div>
        <div className="acts">
          {allowed("projects:manage") && (
            <button className="btn btn-primary" onClick={newProject}>
              <Ic n="plus" s={14} />
              New project
            </button>
          )}
        </div>
      </div>
      <div className="row" style={{ marginBottom: 16, flexWrap: "wrap", gap: 8 }}>
        <div className="inwrap">
          <Ic n="search" s={13} />
          <input
            className="input search-sm"
            placeholder="Search projects"
            value={u.projQ}
            onChange={(e) => set("projQ", e.target.value)}
            aria-label="Search projects"
          />
        </div>
        <select
          className="select"
          style={{ height: 26, width: "auto", fontSize: 12 }}
          value={st}
          onChange={(e) => set("projStatus", e.target.value)}
          aria-label="Filter by status"
        >
          <option value="all">All statuses</option>
          {Object.entries(PSTAT).map(([k, v]) => (
            <option key={k} value={k}>
              {v.name}
            </option>
          ))}
        </select>
        <select
          className="select"
          style={{ height: 26, width: "auto", fontSize: 12 }}
          value={sort}
          onChange={(e) => set("projSort", e.target.value)}
          aria-label="Sort"
        >
          {[
            ["recent", "Recently active"],
            ["name", "Name"],
            ["due", "Due date"],
            ["progress", "Progress"],
          ].map(([k, n]) => (
            <option key={k} value={k}>
              Sort: {n}
            </option>
          ))}
        </select>
        <span className="sp" />
        <div className="seg" role="tablist" aria-label="Layout">
          {(
            [
              ["grid", "Grid", "layout-grid"],
              ["list", "List", "list"],
              ["table", "Table", "table-2"],
            ] as const
          ).map(([k, n, i]) => (
            <button key={k} className={view === k ? "on" : ""} onClick={() => ((u.projView = k), render())} aria-label={n}>
              <Ic n={i} s={13} />
              <span className="hide-m">{n}</span>
            </button>
          ))}
        </div>
      </div>
      {body}
    </div>
  );
}

// The workspace Overview folded into Home.

export { css };
