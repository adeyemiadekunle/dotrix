// Gr8r's table (gr8r-studio/src/views/table.js): every field as a column (choose them, resize them
// by dragging the header edge, sort by clicking it), edit in place, grouped rows; cards on phones.
import { useState, type CSSProperties } from "react";

import { openPop, openTask, updateTask } from "../core/actions";
import { Ic } from "../core/icons";
import { newTask } from "../core/more";
import { fmtDate, iso } from "../core/utils";
import { S, isOver, pColor, proj, render, task, who } from "../data/store";
import type { Project, Task } from "../data/types";
import { TCOLS } from "../overlays/PopLayer";
import { clearFilters, groupTasks, viewChange, viewOf } from "../shell/viewEngine";
import { Av, Due, Empty, Lbl, PrPill, StIcon, StPill } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const popTd = (type: string, t: Task, extra: Record<string, unknown> = {}) => ({
  className: "cellbtn",
  onClick: (e: React.MouseEvent<HTMLElement>) => openPop(e.currentTarget, type, { id: t.id, ...extra }),
});

function EditInput({ t, f, placeholder }: { t: Task; f: "title" | "estimate"; placeholder?: string }) {
  const [v, setV] = useState((t[f] as string) || "");
  const commit = () => {
    S.ui.editCell = null;
    const val = v.trim();
    if (f === "title" ? val && val !== t.title : val !== (t.estimate || "")) updateTask(t.id, { [f]: f === "estimate" ? val || null : val });
    else render();
  };
  return (
    <input
      autoFocus
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") ((S.ui.editCell = null), render());
      }}
      placeholder={placeholder}
      aria-label={f === "title" ? "Title" : "Estimate"}
    />
  );
}

function Cell({ t, c }: { t: Task; c: string }) {
  const ed = S.ui.editCell?.id === t.id && S.ui.editCell.field === c;
  const edit = () => {
    S.ui.editCell = { id: t.id, field: c };
    render();
  };
  switch (c) {
    case "title":
      return ed ? (
        <td className="sticky editing">
          <EditInput t={t} f="title" />
        </td>
      ) : (
        <td className="sticky cellbtn" onClick={() => openTask(t.id)} onDoubleClick={edit} title="Double-click to rename">
          <span className="row" style={{ gap: 8 }}>
            <StIcon st={t.status} s={13} />
            <span className="trunc" style={{ fontWeight: 450 }}>
              {t.title}
            </span>
            <span className="mono faint" style={{ fontSize: 11, marginLeft: "auto" }}>
              {t.key}
            </span>
          </span>
        </td>
      );
    case "status":
      return (
        <td {...popTd("status", t)}>
          <span className="row" style={{ gap: 6 }}>
            <StPill st={t.status} />
          </span>
        </td>
      );
    case "priority":
      return (
        <td {...popTd("priority", t)}>
          <span className="row" style={{ gap: 6 }}>
            <PrPill p={t.priority} />
          </span>
        </td>
      );
    case "assignee":
      return (
        <td {...popTd("assignee", t)}>
          <span className="row" style={{ gap: 6 }}>
            <Av id={t.assignee} cls="sm" tip={false} />
            <span className={`trunc ${t.assignee ? "" : "faint"}`}>{who(t.assignee)?.name || "Unassigned"}</span>
          </span>
        </td>
      );
    case "due":
      return (
        <td {...popTd("date", t, { field: "due" })} style={isOver(t) ? { color: "var(--red)" } : undefined}>
          {t.due ? fmtDate(t.due) : <span className="faint">—</span>}
        </td>
      );
    case "start":
      return <td {...popTd("date", t, { field: "start" })}>{t.start ? fmtDate(t.start) : <span className="faint">—</span>}</td>;
    case "labels":
      return (
        <td {...popTd("labels", t)}>
          <span className="row" style={{ gap: 4 }}>
            {t.labels.length ? t.labels.map((l) => <Lbl key={l} id={l} />) : <span className="faint">—</span>}
          </span>
        </td>
      );
    case "deps":
      return (
        <td {...popTd("deps", t)}>
          {t.deps.length ? (
            t.deps.map((d) =>
              task(d) ? (
                <span key={d} className="depchip" title={task(d)!.title}>
                  {task(d)!.key}
                </span>
              ) : null,
            )
          ) : (
            <span className="faint">—</span>
          )}
        </td>
      );
    case "estimate":
      return ed ? (
        <td className="editing">
          <EditInput t={t} f="estimate" placeholder="e.g. 2d" />
        </td>
      ) : (
        <td className="cellbtn num" onClick={edit} title="Click to edit">
          {t.estimate || <span className="faint">—</span>}
        </td>
      );
    case "created":
      return <td className="num muted">{fmtDate(iso(new Date(t.created)))}</td>;
    case "project":
      return (
        <td {...popTd("project", t)}>
          <span className="row" style={{ gap: 6 }}>
            <span className="pdot" style={css({ "--c": pColor(proj(t.project)) })} />
            <span className="trunc">{proj(t.project)?.name}</span>
          </span>
        </td>
      );
  }
  return <td />;
}

export function Table({ ts, k, p }: { ts: Task[]; k: string; p?: Project }) {
  const v = viewOf(k) as ReturnType<typeof viewOf> & { _projHidden?: boolean };
  if (p && !v._projHidden) {
    v._projHidden = true;
    if (!v.hidden.includes("project")) v.hidden.push("project");
  }
  const cols = TCOLS.filter((c) => c[0] === "title" || !v.hidden.includes(c[0]));
  const w = (c: (typeof TCOLS)[number]) => v.colW[c[0]] || c[2];
  const groups = groupTasks(ts, v.group);
  const totalW = cols.reduce((a, c) => a + w(c), 0);
  if (!ts.length)
    return (
      <Empty icon="search-x" title="No results found" text="No tasks match these filters.">
        <button className="btn btn-secondary btn-sm" onClick={() => clearFilters(k)}>
          Clear filters
        </button>
      </Empty>
    );
  const sortBy = (f: string) => viewChange(k, (vv) => (vv.sort = vv.sort.f === f ? { f, dir: -vv.sort.dir } : { f, dir: 1 }));
  return (
    <>
      <div className="tbl-wrap hide-m">
        <table className="tbl" style={{ width: totalW }} aria-label="Tasks table">
          <colgroup>
            {cols.map((c) => (
              <col key={c[0]} data-col={c[0]} style={{ width: w(c) }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c[0]} className={c[0] === "title" ? "sticky" : ""} style={{ position: "sticky" }} scope="col">
                  <div className="thi" onClick={() => sortBy(["labels", "deps"].includes(c[0]) ? "manual" : c[0])}>
                    {c[1]}
                    {v.sort.f === c[0] && <Ic n={v.sort.dir > 0 ? "arrow-up" : "arrow-down"} s={11} />}
                  </div>
                  <span className="rsz" data-rsz={c[0]} data-key={k} aria-hidden="true" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <GroupRows key={g.key} g={g} cols={cols.map((c) => c[0])} grouped={v.group !== "none"} />
            ))}
            <tr>
              <td className="sticky cellbtn" onClick={() => newTask({ project: p?.id })} colSpan={cols.length} style={{ color: "var(--text-3)" }}>
                <span className="row" style={{ gap: 6 }}>
                  <Ic n="plus" s={14} />
                  New task
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="only-m" style={{ padding: "8px 16px 90px" }}>
        {ts.map((t) => (
          <div key={t.id} className="panel" style={{ padding: 12, marginBottom: 8 }} onClick={() => openTask(t.id)}>
            <div className="row" style={{ marginBottom: 8 }}>
              <StIcon st={t.status} />
              <b style={{ fontWeight: 500 }} className="grow">
                {t.title}
              </b>
              <span className="mono faint" style={{ fontSize: 11 }}>
                {t.key}
              </span>
            </div>
            <div className="row muted" style={{ flexWrap: "wrap", gap: 10, fontSize: 12 }}>
              <PrPill p={t.priority} />
              <Av id={t.assignee} cls="sm" tip={false} />
              <span className="muted">{who(t.assignee)?.name || "Unassigned"}</span>
              <Due t={t} />
              {t.estimate && (
                <span className="faint">
                  <Ic n="timer" s={12} /> {t.estimate}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
function GroupRows({ g, cols, grouped }: { g: ReturnType<typeof groupTasks>[number]; cols: string[]; grouped: boolean }) {
  return (
    <>
      {grouped && (
        <tr className="grow-row">
          <td className="sticky" colSpan={cols.length}>
            <span className="row" style={{ gap: 6 }}>
              {g.html}
              {g.name}
              <span className="faint" style={{ fontWeight: 500 }}>
                {g.tasks.length}
              </span>
            </span>
          </td>
        </tr>
      )}
      {g.tasks.map((t) => (
        <tr
          key={t.id}
          onContextMenu={(e) => {
            e.preventDefault();
            openPop(e.currentTarget, "ctx", { ctx: "task", id: t.id, x: e.clientX, y: e.clientY });
          }}
        >
          {cols.map((c) => (
            <Cell key={c} t={t} c={c} />
          ))}
        </tr>
      ))}
    </>
  );
}
