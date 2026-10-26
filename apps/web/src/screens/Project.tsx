// Project page: header and a tab per view, saved views as
// extra tabs. dotrix adds Knowledge (the project's documents the agents read and keep current).
import type { CSSProperties } from "react";

import { Ic } from "../core/icons";
import { editProject, newTask, openModal, share } from "../core/more";
import { openPop, toggleFavProj } from "../core/actions";
import { PSTAT } from "../core/constants";
import { go, useRoute } from "../core/nav";
import { D, canSee, projByKey, tasksOf } from "../data/store";
import { isLive, live } from "../data/live";
import { useLiveProjectTasks } from "../../lib/workspace-data";
import type { Project as P } from "../data/types";
import { LCOLS, ListView } from "../components/TaskList";
import { applyView, groupTasks, viewOf, ViewToolbar } from "../shell/viewEngine";
import { AvStack, Empty, PIcon } from "../ui/helpers";
import { Board } from "../views/Board";
import { ProjectActivity, ProjectOverview } from "../views/ProjectOverview";
import { Knowledge } from "./Knowledge";

const PTABS: [string, string, string][] = [
  ["overview", "Overview", "layout-dashboard"],
  ["board", "Board", "square-kanban"],
  ["list", "List", "list"],
  ["knowledge", "Knowledge", "book-open"],
  ["activity", "Activity", "activity"],
];

function Denied({ p }: { p: P }) {
  return (
    <div className="page">
      <Empty icon="lock" title="You don't have access" text={`${p.name} is restricted. Ask its lead to add you.`}>
        <button className="btn btn-secondary btn-sm" onClick={() => go("projects")}>
          Back to projects
        </button>
      </Empty>
    </div>
  );
}

const LIST_COLS = ["status", "assignee", "priority", "due", "labels"];

function TaskViewBody({ type, k, p }: { type: string; k: string; p: P }) {
  const v = viewOf(k);
  const liveTasks = useLiveProjectTasks(live.ws?.id, p.id, isLive());
  const base = isLive() ? (liveTasks ?? []) : tasksOf(p.id);
  const ts = applyView(base, v);
  const addBtn = (
    <button className="btn btn-primary btn-sm" onClick={() => newTask({ project: p.id })}>
      <Ic n="plus" s={13} />
      New task
    </button>
  );
  const noTasks = !base.length;
  const emptyAll = (
    <Empty icon="list-checks" title="No tasks here" text="Add a task to get things moving.">
      <button className="btn btn-primary btn-sm" onClick={() => newTask({ project: p.id })}>
        <Ic n="plus" s={14} />
        Add task
      </button>
    </Empty>
  );
  if (type === "board")
    return (
      <>
        <ViewToolbar k={k} group={false} right={addBtn} />
        {noTasks ? emptyAll : <Board ts={ts} k={k} project={p.id} />}
      </>
    );
  // Table folded into List (its columns can be hidden); old Table views and links open List.
  if (type === "list" || type === "table" || type === "calendar" || type === "timeline")
    return (
      <>
        <ViewToolbar k={k} cols={LIST_COLS.map((c) => [c, LCOLS[c]![0]])} right={addBtn} />
        <div className="list-wrap">{noTasks ? emptyAll : <ListView groups={groupTasks(ts, v.group)} k={k} project={p.id} />}</div>
      </>
    );
  return <Empty icon="file-question" title="Page not found" text="That view doesn't exist." />;
}

const svInit: Record<string, boolean> = {};

export function Project() {
  const { params, search } = useRoute();
  const p = projByKey(params.id);
  if (!p) return <Empty icon="file-question" title="Page not found" text="That project doesn't exist or was deleted." />;
  if (!canSee(p)) return <Denied p={p} />;
  // Files moved into Knowledge: old Files links open there.
  const tab = params.tab === "files" ? "knowledge" : params.tab || "board";
  const views = D().savedViews.filter((v) => v.project === p.id);
  const key = "p:" + p.id;
  let body;
  if (tab.startsWith("v:")) {
    const sv = views.find((v) => "v:" + v.id === tab);
    if (!sv) body = <Empty icon="file-question" title="Page not found" text="That saved view was deleted." />;
    else {
      const k = "sv:" + sv.id;
      // A saved view starts from its saved filters the first time it's opened.
      if (!svInit[k]) {
        svInit[k] = true;
        viewOf(k).filters = JSON.parse(JSON.stringify(sv.filters));
      }
      body = <TaskViewBody type={sv.type} k={k} p={p} />;
    }
  } else if (tab === "overview") body = <ProjectOverview p={p} />;
  else if (tab === "knowledge")
    body = (
      <Knowledge
        p={p}
        view={
          params.tab === "files" || search.get("view") === "files"
            ? "files"
            : search.get("view") === "lessons"
              ? "lessons"
              : search.get("view") === "coverage"
                ? "coverage"
                : "docs"
        }
      />
    );
  else if (tab === "activity") body = <ProjectActivity p={p} />;
  else body = <TaskViewBody type={tab} k={key} p={p} />;
  return (
    <div className="page flush">
      <div className="proj-h">
        <div className="t">
          <PIcon p={p} cls="lg" s={18} />
          <h1>{p.name}</h1>
          <button
            className="ibtn ibtn-sm"
            onClick={() => toggleFavProj(p.id)}
            data-tip={p.fav ? "Remove from favorites" : "Add to favorites"}
            aria-pressed={p.fav}
            aria-label="Favorite"
            style={p.fav ? { color: "var(--amber)" } : undefined}
          >
            <Ic n="star" s={15} />
          </button>
          <button
            className="pillbtn bordered"
            onClick={(e) => openPop(e.currentTarget, "pstatus", { id: p.id })}
            aria-label="Project status"
            style={{ height: 24 }}
          >
            <span className="pdot" style={{ "--c": PSTAT[p.status].c, borderRadius: "50%", width: 7, height: 7 } as CSSProperties} />
            {PSTAT[p.status].name}
            <Ic n="chevron-down" s={12} />
          </button>
          <span className="sp" />
          <div className="row" style={{ gap: 4 }}>
            <button className="btn btn-secondary btn-sm hide-m" onClick={() => go("chat", {}, { search: `project=${p.key}` })}>
              <Ic n="message-square" s={13} />
              Ask in Chat
            </button>
            <button className="row" onClick={() => share(p.id)} aria-label="Members" style={{ gap: 0 }}>
              <AvStack ids={p.members} max={5} cls="md" />
            </button>
            <button className="ibtn ibtn-sm" onClick={() => share(p.id)} data-tip="Add member" aria-label="Add member">
              <Ic n="user-plus" s={15} />
            </button>
            <button className="btn btn-secondary btn-sm hide-m" onClick={() => share(p.id)}>
              <Ic n="share-2" s={13} />
              Share
            </button>
            <button className="ibtn ibtn-sm" onClick={() => editProject(p.id)} data-tip="Project settings" aria-label="Project settings">
              <Ic n="settings" s={15} />
            </button>
            <button className="ibtn ibtn-sm" onClick={(e) => openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id })} aria-label="More">
              <Ic n="ellipsis" s={15} />
            </button>
          </div>
        </div>
        <nav className="tabs" aria-label="Project views">
          {PTABS.map(([k, n, i]) => (
            <button
              key={k}
              aria-current={tab === k ? "page" : undefined}
              className={`tab ${tab === k ? "on" : ""}`}
              onClick={() => go("project", { id: p.key, tab: k })}
            >
              <Ic n={i} s={14} />
              {n}
            </button>
          ))}
          {views.map((v) => (
            <button
              key={v.id}
              aria-current={tab === "v:" + v.id ? "page" : undefined}
              className={`tab ${tab === "v:" + v.id ? "on" : ""}`}
              onClick={() => go("project", { id: p.key, tab: "v:" + v.id })}
              onContextMenu={(e) => (e.preventDefault(), openPop(e.currentTarget, "ctx", { ctx: "savedview", vid: v.id }))}
            >
              <Ic n="list-filter" s={14} />
              {v.name}
            </button>
          ))}
          <button
            className="tab"
            onClick={() => openModal({ type: "saveView", pid: p.id, nf: viewOf(key).filters.length })}
            data-tip="Save current filters as a view"
            aria-label="Save view"
          >
            <Ic n="plus" s={14} />
          </button>
        </nav>
      </div>
      <div className="pbody">{body}</div>
    </div>
  );
}
