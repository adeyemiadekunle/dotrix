// Gr8r's shared task list (gr8r-studio/src/components/task-list.js): the editable cells, a row, the
// grouped list with inline add and bulk selection, an activity line, and the small task row.
import { Fragment, useState, type CSSProperties, type MouseEvent, type ReactElement } from "react";

import { openPop, openTask, toggleDone, updateTask } from "../core/actions";
import { PR, ST } from "../core/constants";
import { Ic } from "../core/icons";
import { cancelComposer, commitComposer, confirmDlg, deleteTasks, newTask, notYet, restore, snapshot, startComposer } from "../core/more";
import { go } from "../core/nav";
import { ago, relDate } from "../core/utils";
import { D, S, commentsOf, isOver, logAct, mutate, pColor, proj, render, task, who } from "../data/store";
import type { Activity, Task } from "../data/types";
import { viewChange, type Group } from "../shell/viewEngine";
import { Av, Due, Empty, Lbl, PrIcon, PrPill, StIcon, StPill, TypeIcon } from "../ui/helpers";
import { toast } from "../ui/toast";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const pop = (type: string, t: Task, extra: Record<string, unknown> = {}) => (e: MouseEvent<HTMLElement>) => {
  e.stopPropagation();
  openPop(e.currentTarget, type, { id: t.id, ...extra });
};

export const LCOLS: Record<string, [string, string]> = {
  status: ["Status", "126px"],
  assignee: ["Assignee", "150px"],
  priority: ["Priority", "108px"],
  due: ["Due date", "104px"],
  labels: ["Labels", "168px"],
  project: ["Project", "160px"],
};
export function CellStatus({ t }: { t: Task }) {
  return (
    <button className="pillbtn" onClick={pop("status", t)} aria-label={`Status: ${ST[t.status].name}`}>
      <StPill st={t.status} />
    </button>
  );
}
export function CellAssignee({ t }: { t: Task }) {
  const w = who(t.assignee);
  return (
    <button className={`pillbtn ${w ? "" : "empty"}`} onClick={pop("assignee", t)} aria-label="Assignee">
      <Av id={t.assignee} cls="sm" tip={false} />
      <span className="trunc">{w ? w.name : "Unassigned"}</span>
    </button>
  );
}
export function CellPrio({ t }: { t: Task }) {
  return (
    <button className={`pillbtn ${t.priority === "none" ? "empty" : ""}`} onClick={pop("priority", t)} aria-label="Priority">
      <PrPill p={t.priority} />
    </button>
  );
}
export function CellDue({ t }: { t: Task }) {
  return (
    <button className={`pillbtn ${t.due ? (isOver(t) ? "over" : "") : "empty"}`} onClick={pop("date", t, { field: "due" })} aria-label="Due date">
      <Ic n="calendar" s={13} />
      {t.due ? <span className="num">{relDate(t.due)}</span> : <span>Set date</span>}
    </button>
  );
}
export function CellLabels({ t }: { t: Task }) {
  return (
    <button className={`pillbtn ${t.labels.length ? "" : "empty"}`} onClick={pop("labels", t)} aria-label="Labels" style={{ gap: 4, overflow: "hidden" }}>
      {t.labels.length ? (
        <>
          {t.labels.slice(0, 2).map((l) => (
            <Lbl key={l} id={l} />
          ))}
          {t.labels.length > 2 && (
            <span className="faint" style={{ fontSize: 11 }}>
              +{t.labels.length - 2}
            </span>
          )}
        </>
      ) : (
        <>
          <Ic n="tag" s={13} />
          <span>Add</span>
        </>
      )}
    </button>
  );
}
export function CellProject({ t }: { t: Task }) {
  const p = proj(t.project);
  return (
    <button className="pillbtn" onClick={pop("project", t)} aria-label="Project">
      <span className="pdot" style={css({ "--c": pColor(p) })} />
      <span className="trunc">{p?.name}</span>
    </button>
  );
}
export const CELL: Record<string, (p: { t: Task }) => ReactElement> = {
  status: CellStatus,
  assignee: CellAssignee,
  priority: CellPrio,
  due: CellDue,
  labels: CellLabels,
  project: CellProject,
};

/* ---------- rows ---------- */
const openRows: Record<string, boolean> = {};
function toggleSub(t: Task, sid: string) {
  const s = t.subtasks.find((x) => x.id === sid)!;
  mutate(() => {
    s.done = !s.done;
    logAct(s.done ? "completed a subtask on" : "reopened a subtask on", t, s.title);
  });
}
function TitleCell({ t }: { t: Task }) {
  const editing = S.ui.editCell?.id === t.id && S.ui.editCell.field === "title";
  const [v, setV] = useState(t.title);
  const open = openRows[t.id];
  const cc = commentsOf(t.id).length;
  const sd = t.subtasks.filter((s) => s.done).length;
  const commit = () => {
    S.ui.editCell = null;
    if (v.trim() && v.trim() !== t.title) updateTask(t.id, { title: v.trim() });
    else render();
  };
  return (
    <div
      className="ttl"
      onClick={editing ? undefined : () => openTask(t.id)}
      onDoubleClick={() => {
        S.ui.editCell = { id: t.id, field: "title" };
        setV(t.title);
        render();
      }}
    >
      {t.subtasks.length ? (
        <span
          className="ibtn ibtn-xs"
          onClick={(e) => {
            e.stopPropagation();
            openRows[t.id] = !open;
            render();
          }}
          aria-label={`${open ? "Hide" : "Show"} subtasks`}
          aria-expanded={Boolean(open)}
          style={{ marginLeft: -4 }}
        >
          <Ic n={open ? "chevron-down" : "chevron-right"} s={13} />
        </span>
      ) : (
        <span style={{ width: 18, flexShrink: 0 }} />
      )}
      <span className="key">{t.key}</span>
      {t.type !== "task" && <TypeIcon type={t.type} s={12} />}
      {editing ? (
        <input
          className="inline-in"
          autoFocus
          value={v}
          onChange={(e) => setV(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              S.ui.editCell = null;
              render();
            }
          }}
          aria-label="Task title"
        />
      ) : (
        <span className="tt">{t.title}</span>
      )}
      {t.recur && (
        <span className="meta-mini" data-tip={`Repeats ${t.recur.toLowerCase()}`}>
          <Ic n="repeat" s={11} />
        </span>
      )}
      {t.subtasks.length > 0 && (
        <span className="meta-mini">
          <Ic n="list-checks" s={11} />
          {sd}/{t.subtasks.length}
        </span>
      )}
      {cc > 0 && (
        <span className="meta-mini">
          <Ic n="message-square" s={11} />
          {cc}
        </span>
      )}
    </div>
  );
}
export function TaskRow({ t, cols, tpl, group, complete, drag = true }: { t: Task; cols: string[]; tpl: string; group?: string; complete?: boolean; drag?: boolean }) {
  const sel = S.ui.sel.has(t.id);
  return (
    <>
      <div
        className={`trow ${t.status === "done" ? "done" : ""} ${sel ? "sel" : ""}`}
        style={css({ "--cols": tpl })}
        data-group={group}
        onContextMenu={(e) => {
          e.preventDefault();
          openPop(e.currentTarget, "ctx", { ctx: "task", id: t.id, x: e.clientX, y: e.clientY });
        }}
      >
        <div className="handle" aria-hidden="true">
          {drag && <Ic n="grip-vertical" s={14} />}
        </div>
        <div className="c-check">
          {complete ? (
            <input type="checkbox" className="check round" checked={t.status === "done"} onChange={() => toggleDone(t.id)} aria-label={`Mark ${t.title} complete`} />
          ) : (
            <input
              type="checkbox"
              className="check"
              checked={sel}
              onChange={() => {
                if (sel) S.ui.sel.delete(t.id);
                else S.ui.sel.add(t.id);
                render();
              }}
              aria-label={`Select ${t.title}`}
            />
          )}
        </div>
        <TitleCell t={t} />
        {cols.map((c) => {
          const C = CELL[c]!;
          return (
            <div key={c} className={`c-meta c-${c === "labels" ? "lbl" : c}`}>
              <C t={t} />
            </div>
          );
        })}
        <div className="c-more">
          <button className="ibtn ibtn-sm" onClick={(e) => openPop(e.currentTarget, "ctx", { ctx: "task", id: t.id })} aria-label="More actions">
            <Ic n="ellipsis" s={15} />
          </button>
        </div>
      </div>
      {openRows[t.id] && (
        <div className="subrows">
          {t.subtasks.map((s) => (
            <div key={s.id} className={`subrow ${s.done ? "done" : ""}`}>
              <input type="checkbox" className="check" checked={s.done} onChange={() => toggleSub(t, s.id)} aria-label="Complete subtask" />
              <span>{s.title}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function Composer({ k, g }: { k: string; g: Group }) {
  const [v, setV] = useState("");
  return (
    <div className="addrow" style={{ background: "var(--surface-2)" }}>
      <Ic n="plus" s={14} />
      <input
        className="inline-in"
        autoFocus
        value={v}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            commitComposer(v);
            setV("");
          }
          if (e.key === "Escape") cancelComposer();
        }}
        onBlur={() => !v && cancelComposer()}
        placeholder="Task name — press Enter to add, Esc to cancel"
        aria-label="New task name"
      />
      <span hidden>{g.key}</span>
    </div>
  );
}

export function ListView({
  groups,
  k,
  cols = ["status", "assignee", "priority", "due", "labels"],
  complete,
  noAdd,
  project,
  drag,
}: {
  groups: Group[];
  k: string;
  cols?: string[];
  complete?: boolean;
  noAdd?: boolean;
  project?: string;
  drag?: boolean;
}) {
  const tpl = `18px 30px minmax(220px,1fr) ${cols.map((c) => LCOLS[c]![1]).join(" ")} 40px`;
  const all = groups.flatMap((g) => g.tasks.map((t) => t.id));
  const nSel = all.filter((id) => S.ui.sel.has(id)).length;
  const total = all.length;
  if (!total)
    return (
      <Empty icon="list-checks" title="No tasks here" text="Add a task to get things moving.">
        <button className="btn btn-primary btn-sm" onClick={() => newTask({ project })}>
          <Ic n="plus" s={14} />
          New task
        </button>
      </Empty>
    );
  const v = S.views[k];
  const sortBy = (f: string) =>
    viewChange(k, (vv) => {
      vv.sort = vv.sort.f === f ? { f, dir: -vv.sort.dir } : { f, dir: 1 };
    });
  return (
    <>
      <div className="tlist" role="table" aria-label="Tasks">
        <div className="thead" style={css({ "--cols": tpl })} role="row">
          <div />
          <div>
            {!complete && (
              <input
                type="checkbox"
                className="check"
                checked={nSel > 0 && nSel === total}
                ref={(el) => {
                  if (el) el.indeterminate = nSel > 0 && nSel < total;
                }}
                onChange={() => {
                  if (nSel === total) all.forEach((id) => S.ui.sel.delete(id));
                  else all.forEach((id) => S.ui.sel.add(id));
                  render();
                }}
                aria-label="Select all"
              />
            )}
          </div>
          <div onClick={() => sortBy("title")} style={{ cursor: "pointer" }}>
            Task {v?.sort.f === "title" && <Ic n={v.sort.dir > 0 ? "arrow-up" : "arrow-down"} s={11} />}
          </div>
          {cols.map((c) => (
            <div key={c} onClick={() => sortBy(c === "labels" ? "manual" : c)} style={{ cursor: "pointer" }}>
              {LCOLS[c]![0]} {v?.sort.f === c && <Ic n={v.sort.dir > 0 ? "arrow-up" : "arrow-down"} s={11} />}
            </div>
          ))}
          <div />
        </div>
        {groups.map((g) => {
          const gk = k + ":" + g.key;
          const coll = S.ui.collapsedGroups[gk] ?? false;
          const comp = S.ui.composer && S.ui.composer.key === k && S.ui.composer.group === g.key;
          return (
            <Fragment key={g.key}>
              {(groups.length > 1 || g.key !== "all") && (
                <div className="grp">
                  <button
                    className="ibtn ibtn-xs"
                    onClick={() => {
                      S.ui.collapsedGroups[gk] = !coll;
                      render();
                    }}
                    aria-expanded={!coll}
                    aria-label="Toggle group"
                  >
                    <Ic n={coll ? "chevron-right" : "chevron-down"} s={13} />
                  </button>
                  {g.html}
                  <span>{g.name}</span>
                  <span className="cnt">{g.tasks.length}</span>
                  {!noAdd && (
                    <button className="ibtn ibtn-xs" onClick={() => startComposer(k, g.key, g.set || {})} aria-label={`Add task to ${g.name}`}>
                      <Ic n="plus" s={13} />
                    </button>
                  )}
                </div>
              )}
              {!coll && g.tasks.map((t) => <TaskRow key={t.id} t={t} cols={cols} tpl={tpl} group={g.key} complete={complete} drag={drag !== false} />)}
              {!coll &&
                !noAdd &&
                (comp ? (
                  <Composer k={k} g={g} />
                ) : (
                  <button className="addrow" onClick={() => startComposer(k, g.key, g.set || {})}>
                    <Ic n="plus" s={14} />
                    Add task
                  </button>
                ))}
            </Fragment>
          );
        })}
      </div>
      <BulkBar ids={all} />
    </>
  );
}
export function BulkBar({ ids }: { ids: string[] }) {
  const n = ids.filter((id) => S.ui.sel.has(id)).length;
  if (!n) return null;
  const del = () => {
    const sel = [...S.ui.sel];
    confirmDlg({
      title: `Delete ${sel.length} task${sel.length > 1 ? "s" : ""}?`,
      body: "They and their comments will be permanently deleted.",
      ok: "Delete",
      danger: true,
      run: () => {
        if (notYet("Deleting issues")) return;
        const snap = snapshot();
        mutate(() => deleteTasks(sel));
        toast(`Deleted ${sel.length} task${sel.length > 1 ? "s" : ""}`, { action: "Undo", onAction: () => restore(snap) });
      },
    });
  };
  return (
    <div className="bulkbar enter" role="toolbar" aria-label="Bulk actions">
      <b style={{ fontWeight: 600 }}>{n} selected</b>
      <span className="sep" />
      <button className="btn btn-sm" onClick={(e) => openPop(e.currentTarget, "bulk-status")}>
        <Ic n="circle-dot" s={14} />
        Status
      </button>
      <button className="btn btn-sm" onClick={(e) => openPop(e.currentTarget, "bulk-assignee")}>
        <Ic n="user" s={14} />
        Assignee
      </button>
      <button className="btn btn-sm" onClick={(e) => openPop(e.currentTarget, "bulk-priority")}>
        <Ic n="signal-high" s={14} />
        Priority
      </button>
      <button className="btn btn-sm" onClick={del}>
        <Ic n="trash-2" s={14} />
        Delete
      </button>
      <span className="sep" />
      <button
        className="btn btn-sm"
        onClick={() => {
          S.ui.sel.clear();
          render();
        }}
        aria-label="Clear selection"
      >
        <Ic n="x" s={14} />
      </button>
    </div>
  );
}

/* ---------- activity, small rows ---------- */
export function ActItem({ a, withProject }: { a: Activity; withProject?: boolean }) {
  const w = who(a.by);
  const t = a.task ? task(a.task) : null;
  const p = a.project ? proj(a.project) : null;
  return (
    <div className="fitem">
      <Av id={a.by} cls="sm" />
      <div className="grow">
        <b>{a.by === D().me ? "You" : w?.name || "Someone"}</b> <span className="muted">{a.verb}</span>{" "}
        {t ? (
          <span className="obj" onClick={() => openTask(t.id)}>
            {t.title}
          </span>
        ) : p ? (
          <span className="obj" onClick={() => go("project", { id: p.key })}>
            {p.name}
          </span>
        ) : null}{" "}
        {a.extra && <span className="muted">{a.extra}</span>}
        {withProject && p && t && <span className="faint"> in {p.name}</span>}
      </div>
      <time>{ago(a.at)}</time>
    </div>
  );
}
export function MiniRow({ t, av = true, noProj }: { t: Task; av?: boolean; noProj?: boolean }) {
  const p = proj(t.project);
  return (
    <div
      className={`mini ${t.status === "done" ? "done" : ""}`}
      onClick={() => openTask(t.id)}
      onContextMenu={(e) => {
        e.preventDefault();
        openPop(e.currentTarget, "ctx", { ctx: "task", id: t.id });
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && openTask(t.id)}
    >
      <input
        type="checkbox"
        className="check round"
        checked={t.status === "done"}
        onClick={(e) => e.stopPropagation()}
        onChange={() => toggleDone(t.id)}
        aria-label={`Complete ${t.title}`}
      />
      <span data-tip={ST[t.status].name}>
        <StIcon st={t.status} />
      </span>
      <span className="tt">{t.title}</span>
      {!noProj && (
        <span className="pj hide-m">
          <span className="pdot" style={css({ "--c": pColor(p) })} />
          <span className="trunc">{p?.name}</span>
        </span>
      )}
      <span data-tip={`${PR[t.priority].name} priority`}>
        <PrIcon p={t.priority} />
      </span>
      <span style={{ width: 74, textAlign: "right" }} className="hide-m">
        <Due t={t} icon={false} />
      </span>
      {av && <Av id={t.assignee} cls="sm" />}
    </div>
  );
}
