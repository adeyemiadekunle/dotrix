import { TabList, Tab } from "@dotrix/ui/astryx";
import { Input as DesignInput } from "@dotrix/ui/components/input";
import { ActionButton } from "@dotrix/ui/components/action-button";
// Projects. The workspace Overview folded into Home.

import { openPop } from "../core/actions";
import { PSTAT } from "../core/constants";
import { allowed } from "../core/can";
import { personal } from "../core/features";
import { Ic } from "../core/icons";
import { newProject } from "../core/more";
import { go } from "../core/nav";
import { ago, fmtDate, minsAgo } from "../core/utils";
import { S, canSee, mem, progressOf, render } from "../data/store";
import { useProjects } from "../data/lists";
import { useAllTasks, useProjectTasks } from "../data/tasks";
import type { Project } from "../data/types";
import { Av, AvStack, Empty, PIcon, PStatus, ProgBar } from "../ui/helpers";

const ctx = (p: Project) => (e: React.MouseEvent<HTMLElement>) => {
  e.preventDefault();
  openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id, x: e.clientX, y: e.clientY });
};
const more = (p: Project) => (e: React.MouseEvent<HTMLElement>) => {
  e.stopPropagation();
  openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id });
};

function ProjectCard({ p }: { p: Project }) {
  const { tasks: ts } = useProjectTasks(p.id);
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
        {!personal() && <AvStack ids={p.members} max={3} />}
      </div>
      <ActionButton
        className="ibtn ibtn-sm more"
        onClick={more(p)}
        aria-label="Project options"
        style={{ background: "var(--surface)", boxShadow: "0 0 0 1px var(--border)" }}
      >
        <Ic n="ellipsis" s={14} />
      </ActionButton>
    </div>
  );
}

export function Projects() {
  const u = S.ui;
  const q = u.projQ.toLowerCase();
  const st = u.projStatus;
  const sort = u.projSort;
  const { items: projects } = useProjects();
  const { tasks } = useAllTasks();
  const count = (pid: string) => tasks.filter((t) => t.project === pid).length;
  const base = projects.filter((p) => canSee(p));
  const ps = base.filter((p) => (st === "all" || p.status === st) && (!q || p.name.toLowerCase().includes(q) || p.desc.toLowerCase().includes(q)));
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
  if (!base.length)
    body = (
      <div className="panel">
        <Empty icon="folder-kanban" title="No projects yet" text="Create your first project to start organizing your work.">
          {allowed("projects:manage") && (
            <ActionButton className="btn btn-primary btn-sm" onClick={newProject}>
              <Ic n="plus" s={14} />
              Create project
            </ActionButton>
          )}
        </Empty>
      </div>
    );
  else if (!ps.length)
    body = (
      <div className="panel">
        <Empty icon="search-x" title="No results found" text="No projects match your search or filters. Try a different term.">
          <ActionButton className="btn btn-secondary btn-sm" onClick={() => ((u.projQ = ""), (u.projStatus = "all"), render())}>
            Clear filters
          </ActionButton>
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
              {!personal() && <AvStack ids={p.members} max={3} />}
              <ActionButton className="ibtn ibtn-sm" onClick={more(p)} aria-label="Options">
                <Ic n="ellipsis" s={14} />
              </ActionButton>
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
              {!personal() && <th style={{ textAlign: "left" }}>Lead</th>}
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
                  {!personal() && (
                    <td style={{ textAlign: "left" }}>
                      <span className="row">
                        <Av id={p.lead} cls="sm" />
                        {mem(p.lead)?.name}
                      </span>
                    </td>
                  )}
                  <td>
                    <span className="row">
                      <ProgBar v={pr} />
                      <span className="num faint" style={{ fontSize: 11.5 }}>
                        {pr}%
                      </span>
                    </span>
                  </td>
                  <td className="num">{count(p.id)}</td>
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
                    <ActionButton className="ibtn ibtn-sm" onClick={more(p)} aria-label="Options">
                      <Ic n="ellipsis" s={14} />
                    </ActionButton>
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
            {projects.filter((p) => p.status !== "complete").length} active · {projects.filter((p) => p.status === "complete").length} completed
          </p>
        </div>
        <div className="acts">
          {allowed("projects:manage") && (
            <ActionButton className="btn btn-primary" onClick={newProject}>
              <Ic n="plus" s={14} />
              New project
            </ActionButton>
          )}
        </div>
      </div>
      <div className="row" style={{ marginBottom: 16, flexWrap: "wrap", gap: 8 }}>
        <div className="inwrap">
          <Ic n="search" s={13} />
          <DesignInput
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
        <TabList
          aria-label="Layout"
          value={view}
          onChange={(value) => {
            u.projView = value as typeof view;
            render();
          }}
          size="sm"
        >
          {(
            [
              ["grid", "Grid", "layout-grid"],
              ["list", "List", "list"],
              ["table", "Table", "table-2"],
            ] as const
          ).map(([key, label, icon]) => (
            <Tab key={key} value={key} label={label} icon={<Ic n={icon} s={13} />} />
          ))}
        </TabList>
      </div>
      {body}
    </div>
  );
}

// The workspace Overview folded into Home.
