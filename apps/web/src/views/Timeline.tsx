// Gr8r's timeline (gr8r-studio/src/views/timeline.js): bars from start to due date by week or
// month, grouped, with milestones and dependency arrows; drag a bar to move it (core/dragdrop).
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

import { openTask } from "../core/actions";
import { suppressClick } from "../core/dragdrop";
import { Ic } from "../core/icons";
import { newTask } from "../core/more";
import { MON, MONL, TODAY, addD, diffD, fmtDate, parse } from "../core/utils";
import { S, canSee, pColor, proj, render, task, taskProg, visibleProjects } from "../data/store";
import type { Milestone, Project, Task } from "../data/types";
import { startOfWeek } from "../overlays/PopLayer";
import { groupTasks, type Group } from "../shell/viewEngine";
import { Av, Empty, StIcon } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const scrolledToToday: Record<string, boolean> = {};

export function TlControls() {
  return (
    <>
      <div className="seg" style={{ marginLeft: 4 }}>
        {(
          [
            ["week", "Weeks"],
            ["month", "Months"],
          ] as const
        ).map(([k, n]) => (
          <button key={k} className={S.ui.tlZoom === k ? "on" : ""} onClick={() => ((S.ui.tlZoom = k), render())}>
            {n}
          </button>
        ))}
      </div>
      <select className="select" style={{ height: 26, width: "auto", fontSize: 12, marginLeft: 4 }} value={S.ui.tlGroup} onChange={(e) => ((S.ui.tlGroup = e.target.value), render())} aria-label="Group by">
        {[
          ["status", "Group: Status"],
          ["assignee", "Group: Assignee"],
          ["project", "Group: Project"],
          ["none", "No grouping"],
        ].map(([k, n]) => (
          <option key={k} value={k}>
            {n}
          </option>
        ))}
      </select>
      <button
        className="btn btn-ghost"
        onClick={() => {
          const r = document.getElementById("tl-right");
          const tl = document.querySelector<HTMLElement>(".tl");
          if (r && tl) r.scrollTo({ left: Math.max(0, +tl.dataset.tlToday! - 160), behavior: "smooth" });
        }}
      >
        <Ic n="crosshair" s={14} />
        Today
      </button>
    </>
  );
}

type MsP = Milestone & { p?: Project };
function MsLane({ ms, X, dw, y }: { ms: MsP[]; X: (d: string) => number; dw: number; y: number }) {
  const byDate: Record<string, MsP[]> = {};
  ms.forEach((m) => (byDate[m.date] ||= []).push(m));
  const pts = Object.entries(byDate)
    .sort(([a], [b]) => (a > b ? 1 : -1))
    .map(([date, list]) => ({ date, list, x: X(date) + dw / 2 }));
  return (
    <>
      {pts.map((pt, i) => {
        const room = (pts[i + 1] ? pts[i + 1]!.x : Infinity) - pt.x - 24;
        const first = pt.list[0]!;
        const name = first.name + (pt.list.length > 1 ? ` +${pt.list.length - 1}` : "");
        const tip = pt.list.map((m) => m.name + (m.p ? ` (${m.p.name})` : "")).join(" · ") + " · " + fmtDate(pt.date);
        return (
          <div key={pt.date} className="ms-w" style={{ left: pt.x - 6, top: y + 9 }} data-tip={tip} tabIndex={0} aria-label={`Milestone: ${tip}`}>
            <span className="ms" style={first.p ? { background: pColor(first.p) } : undefined} />
            {room >= 28 && (
              <span className="ms-l" style={{ maxWidth: Number.isFinite(room) ? Math.round(room) : "none" }}>
                {name}
              </span>
            )}
          </div>
        );
      })}
    </>
  );
}

export function Timeline({ ts, k, p }: { ts: Task[]; k: string; p?: Project | null }) {
  const right = useRef<HTMLDivElement>(null);
  const left = useRef<HTMLDivElement>(null);
  const dw = S.ui.tlZoom === "week" ? 32 : 11;
  const rs = startOfWeek(addD(TODAY, S.ui.tlZoom === "week" ? -21 : -56));
  const nDays = S.ui.tlZoom === "week" ? 7 * 13 : 7 * 34;
  const X = (ds: string) => diffD(parse(ds)!, rs) * dw;
  const g = S.ui.tlGroup;
  const groups = groupTasks(
    ts.filter((t) => t.due),
    g === "project" && p ? "status" : g,
  ).filter((G) => G.tasks.length);
  type Row = { type: "ms" } | { type: "g"; G: Group } | { type: "t"; t: Task };
  const rows: Row[] = [];
  const ms: MsP[] = p
    ? p.milestones || []
    : visibleProjects()
        .filter(canSee)
        .flatMap((q) => (q.milestones || []).map((m) => ({ ...m, p: q })));
  if (ms.length) rows.push({ type: "ms" });
  groups.forEach((G) => {
    if (g !== "none") rows.push({ type: "g", G });
    G.tasks.sort((a, b) => ((a.start || a.due)! > (b.start || b.due)! ? 1 : -1)).forEach((t) => rows.push({ type: "t", t }));
  });
  const RH = 36;
  const H = rows.length * RH;
  const W = nDays * dw;
  const rowY: Record<string, number> = {};
  rows.forEach((r, i) => {
    if (r.type === "t") rowY[r.t.id] = i * RH + RH / 2;
  });
  const todayX = diffD(TODAY, rs) * dw;
  useEffect(() => {
    const r = right.current;
    const l = left.current;
    if (!r || !l) return;
    r.onscroll = () => (l.scrollTop = r.scrollTop);
    const key = k + S.ui.tlZoom;
    if (!scrolledToToday[key]) {
      scrolledToToday[key] = true;
      r.scrollLeft = Math.max(0, todayX - 160);
    }
  });
  if (!rows.length)
    return (
      <Empty icon="chart-gantt" title="Nothing on the timeline" text="Give tasks a start and due date to see them here.">
        <button className="btn btn-primary btn-sm" onClick={() => newTask({ project: p?.id })}>
          <Ic n="plus" s={14} />
          New task
        </button>
      </Empty>
    );
  const months: { d: Date; n: number }[] = [];
  let cm: string | null = null;
  for (let i = 0; i < nDays; i++) {
    const d = addD(rs, i);
    const key = d.getMonth() + "-" + d.getFullYear();
    if (key !== cm) {
      months.push({ d, n: 0 });
      cm = key;
    }
    months[months.length - 1]!.n++;
  }
  const open = (id: string) => !suppressClick && openTask(id);
  const bars: ReactNode[] = rows.map((r, i) => {
    const y = i * RH;
    if (r.type === "g") return <div key={`g${i}`} className="tl-rowbg g" style={{ top: y }} />;
    if (r.type === "ms")
      return (
        <span key="ms" style={{ display: "contents" }}>
          <div className="tl-rowbg" style={{ top: y }} />
          <MsLane ms={ms} X={X} dw={dw} y={y} />
        </span>
      );
    const t = r.t;
    const pp = proj(t.project);
    const s = t.start && t.start <= t.due! ? t.start : t.due!;
    const x = X(s);
    const w = Math.max(dw, (diffD(parse(t.due)!, parse(s)!) + 1) * dw);
    const c = g === "status" || g === "none" ? pColor(pp) : `var(--st-${t.status})`;
    const inside = w > 110;
    return (
      <span key={t.id} style={{ display: "contents" }}>
        <div className="tl-rowbg" style={{ top: y }} />
        <div
          className={`bar ${t.status === "done" ? "done" : ""}`}
          style={css({ "--c": c, left: x, top: y + 7, width: w })}
          data-bar={t.id}
          data-dw={dw}
          onClick={() => open(t.id)}
          title={`${t.title} · ${fmtDate(s)} → ${fmtDate(t.due)}`}
        >
          <span className="pf" style={{ width: `${taskProg(t)}%` }} />
          {inside && (
            <>
              <Av id={t.assignee} cls="sm" tip={false} />
              <span className="trunc">{t.title}</span>
            </>
          )}
        </div>
        {!inside && (
          <div className="bar-lbl" style={{ left: x + w + 8, top: y + 10 }}>
            {t.title}
          </div>
        )}
      </span>
    );
  });
  const deps = ts.flatMap((t) =>
    t.deps
      .filter((d) => rowY[d] != null && rowY[t.id] != null)
      .map((d) => {
        const a = task(d)!;
        const x1 = X(a.due!) + dw;
        const y1 = rowY[d]!;
        const s = t.start && t.start <= t.due! ? t.start : t.due!;
        const x2 = X(s);
        const y2 = rowY[t.id]!;
        const mx = Math.max(x1 + 10, x2 - 10);
        return (
          <g key={`${d}-${t.id}`}>
            <path d={`M${x1} ${y1} C ${mx} ${y1}, ${Math.min(x1 + 10, x2 - 10)} ${y2}, ${x2 - 1} ${y2}`} fill="none" stroke="var(--text-3)" strokeWidth="1.3" strokeDasharray={x2 < x1 ? "3 3" : undefined} />
            <path d={`M${x2 - 6} ${y2 - 3.5} L${x2 - 1} ${y2} L${x2 - 6} ${y2 + 3.5}`} fill="none" stroke="var(--text-3)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
          </g>
        );
      }),
  );
  return (
    <div className="tl" data-tl-today={todayX}>
      <div className="tl-left">
        <div className="tl-head">Task</div>
        <div className="tl-rows" id="tl-rows" ref={left}>
          {rows.map((r, i) => {
            if (r.type === "ms")
              return (
                <div key="ms" className="tl-row g">
                  <Ic n="diamond" s={12} />
                  Milestones
                  <span className="faint" style={{ fontWeight: 500 }}>
                    {ms.length}
                  </span>
                </div>
              );
            if (r.type === "g")
              return (
                <div key={`g${i}`} className="tl-row g">
                  {r.G.html}
                  {r.G.name}
                  <span className="faint" style={{ fontWeight: 500 }}>
                    {r.G.tasks.length}
                  </span>
                </div>
              );
            const t = r.t;
            return (
              <div key={t.id} className="tl-row" onClick={() => openTask(t.id)}>
                <StIcon st={t.status} s={13} />
                <span className="trunc grow" style={t.status === "done" ? { color: "var(--text-3)" } : undefined}>
                  {t.title}
                </span>
                {t.subtasks.length > 0 && (
                  <span className="faint num" style={{ fontSize: 11 }}>
                    {t.subtasks.filter((s) => s.done).length}/{t.subtasks.length}
                  </span>
                )}
                <Av id={t.assignee} cls="sm" />
              </div>
            );
          })}
          <div style={{ height: 40 }} />
        </div>
      </div>
      <div className="tl-right" id="tl-right" ref={right}>
        <div className="tl-head" style={{ width: W }}>
          <div className="tl-months">
            {months.map((m, i) => (
              <div key={i} style={{ width: m.n * dw }}>
                <span>
                  {MONL[m.d.getMonth()]} {m.d.getFullYear()}
                </span>
              </div>
            ))}
          </div>
          <div className="tl-days">
            {S.ui.tlZoom === "week"
              ? Array.from({ length: nDays }, (_, i) => {
                  const d = addD(rs, i);
                  return (
                    <div key={i} style={{ width: dw }} className={diffD(d, TODAY) === 0 ? "today" : ""}>
                      {d.getDate()}
                    </div>
                  );
                })
              : Array.from({ length: nDays / 7 }, (_, i) => {
                  const d = addD(rs, i * 7);
                  return (
                    <div key={i} style={{ width: dw * 7 }}>
                      {MON[d.getMonth()]} {d.getDate()}
                    </div>
                  );
                })}
          </div>
        </div>
        <div className="tl-grid" style={{ width: W, height: H + 40 }}>
          {S.ui.tlZoom === "week" &&
            Array.from({ length: nDays }, (_, i) => {
              const d = addD(rs, i);
              return d.getDay() === 0 || d.getDay() === 6 ? <div key={i} className="tl-we" style={{ left: i * dw, width: dw }} /> : null;
            })}
          {Array.from({ length: nDays / 7 }, (_, i) => (
            <div key={`gl${i}`} className="tl-gl" style={{ left: i * 7 * dw }} />
          ))}
          <div className="tl-today" style={{ left: todayX + dw / 2 }} title="Today" />
          {bars}
          <svg className="tl-deps" width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
            {deps}
          </svg>
        </div>
      </div>
    </div>
  );
}
