// Gr8r's calendar (gr8r-studio/src/views/calendar.js): month or week, tasks on their due dates and
// events; drag a task to another day to reschedule it (core/dragdrop).
import type { CSSProperties } from "react";

import { openPop, openTask } from "../core/actions";
import { Ic } from "../core/icons";
import { newTask } from "../core/more";
import { MONL, TODAY, WD, addD, diffD, fmtDate, iso, parse } from "../core/utils";
import { D, S, pColor, proj, render } from "../data/store";
import type { CalEvent, Task } from "../data/types";
import { startOfWeek } from "../overlays/PopLayer";
import { Av, PrIcon, StIcon } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;
type Item = { ev: CalEvent; t?: undefined } | { t: Task; ev?: undefined };

function calNav(d: number) {
  const cur = parse(S.ui.calDate)!;
  if (d === 0) S.ui.calDate = iso(TODAY);
  else if (S.ui.calMode === "month") S.ui.calDate = iso(new Date(cur.getFullYear(), cur.getMonth() + d, 1));
  else S.ui.calDate = iso(addD(cur, 7 * d));
  render();
}

export function Calendar({ ts, k = "", project, events }: { ts: Task[]; k?: string; project?: string; events?: boolean }) {
  const cur = parse(S.ui.calDate)!;
  const mode = S.ui.calMode;
  const evs = events ? D().events.filter((e) => !project || e.project === project) : [];
  const itemsOn = (ds: string): Item[] => [...evs.filter((e) => e.date === ds).map((ev) => ({ ev })), ...ts.filter((t) => t.due === ds).map((t) => ({ t }))];
  const wdn = Array.from({ length: 7 }, (_, i) => WD[(i + S.prefs.weekStart) % 7]!);
  const chip = (it: Item) => {
    if (it.ev) {
      const p = proj(it.ev.project);
      return (
        <button
          key={it.ev.id}
          className="cev event"
          style={css({ "--c": pColor(p) })}
          onClick={(e) => openPop(e.currentTarget, "event", { id: it.ev!.id })}
          title={`${it.ev.title} · ${it.ev.time}`}
        >
          <span className="num faint" style={{ fontSize: 11 }}>
            {it.ev.time}
          </span>
          <span className="trunc">{it.ev.title}</span>
        </button>
      );
    }
    const t = it.t!;
    const p = proj(t.project);
    return (
      <button key={t.id} className={`cev ${t.status === "done" ? "done" : ""}`} style={css({ "--c": pColor(p) })} draggable data-drag-cal={t.id} onClick={() => openTask(t.id)} title={t.title}>
        {t.status === "done" ? <StIcon st="done" s={11} /> : <PrIcon p={t.priority} s={11} />}
        <span className="trunc">{t.title}</span>
        <Av id={t.assignee} tip={false} />
      </button>
    );
  };
  let label: string;
  let body;
  if (mode === "month") {
    label = `${MONL[cur.getMonth()]} ${cur.getFullYear()}`;
    const start = startOfWeek(new Date(cur.getFullYear(), cur.getMonth(), 1));
    const cells = Array.from({ length: 42 }, (_, i) => addD(start, i));
    const trimmed = cells[35]!.getMonth() !== cur.getMonth() ? cells.slice(0, 35) : cells;
    body = (
      <>
        <div className="cal-h">
          {wdn.map((d) => (
            <div key={d}>{d}</div>
          ))}
        </div>
        <div className="cal-g" style={{ gridTemplateRows: `repeat(${trimmed.length / 7},minmax(112px,1fr))` }}>
          {trimmed.map((d) => {
            const ds = iso(d);
            const items = itemsOn(ds);
            const today = diffD(d, TODAY) === 0;
            return (
              <div key={ds} className={`cday ${d.getMonth() !== cur.getMonth() ? "out" : ""} ${today ? "today" : ""}`} data-drop-day={ds}>
                <span className="dn" aria-current={today ? "date" : undefined}>
                  {d.getDate()}
                </span>
                <button className="ibtn ibtn-xs add" onClick={() => newTask({ due: ds, project })} aria-label={`Add task on ${fmtDate(ds)}`}>
                  <Ic n="plus" s={13} />
                </button>
                {items.slice(0, 3).map(chip)}
                {items.length > 3 && (
                  <button className="cmore" onClick={(e) => openPop(e.currentTarget, "daylist", { date: ds, key: k })}>
                    +{items.length - 3} more
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </>
    );
  } else {
    const ws = startOfWeek(cur);
    const days = Array.from({ length: 7 }, (_, i) => addD(ws, i));
    label = `${fmtDate(iso(days[0]!))} – ${fmtDate(iso(days[6]!))}, ${days[6]!.getFullYear()}`;
    body = (
      <div className="week">
        {days.map((d) => {
          const ds = iso(d);
          const items = itemsOn(ds).sort((a, b) => (a.ev ? 0 : 1) - (b.ev ? 0 : 1));
          const today = diffD(d, TODAY) === 0;
          return (
            <div key={ds} className="wcol">
              <div className={`wcol-h ${today ? "today" : ""}`}>
                <span className="n">{d.getDate()}</span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {WD[d.getDay()]}
                </span>
                <span className="sp" />
                <button className="ibtn ibtn-xs" onClick={() => newTask({ due: ds, project })} aria-label="Add task">
                  <Ic n="plus" s={13} />
                </button>
              </div>
              <div className="wcol-b" data-drop-day={ds}>
                {items.length ? (
                  items.map((it) => {
                    if (it.ev) {
                      const p = proj(it.ev.project)!;
                      return (
                        <button key={it.ev.id} className="wcard event" style={css({ "--c": pColor(p) })} onClick={(e) => openPop(e.currentTarget, "event", { id: it.ev!.id })}>
                          <span className="t">
                            <span className="pdot" style={css({ "--c": pColor(p), borderRadius: "50%" })} />
                            {it.ev.title}
                          </span>
                          <span className="m">
                            <Ic n="clock" s={11} />
                            {it.ev.time} · {p.name}
                          </span>
                        </button>
                      );
                    }
                    const t = it.t!;
                    const p = proj(t.project)!;
                    return (
                      <button key={t.id} className="wcard" style={css({ "--c": pColor(p) })} draggable data-drag-cal={t.id} onClick={() => openTask(t.id)}>
                        <span className="t" style={t.status === "done" ? { textDecoration: "line-through", color: "var(--text-3)" } : undefined}>
                          <span className="pdot" style={css({ "--c": pColor(p) })} />
                          {t.title}
                        </span>
                        <span className="m">
                          <StIcon st={t.status} s={11} />
                          <PrIcon p={t.priority} s={11} />
                          <span className="trunc grow">{p.name}</span>
                          <Av id={t.assignee} cls="sm" tip={false} />
                        </span>
                      </button>
                    );
                  })
                ) : (
                  <span className="faint" style={{ fontSize: 12, padding: 4 }}>
                    No tasks
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  }
  const projs = [...new Set(ts.map((t) => t.project))].map(proj).filter(Boolean);
  return (
    <div className="cal" style={{ minHeight: 640 }}>
      <div className="toolbar" style={{ gap: 8 }}>
        <button className="btn btn-secondary btn-sm" onClick={() => calNav(0)}>
          Today
        </button>
        <div className="row" style={{ gap: 0 }}>
          <button className="ibtn ibtn-sm" onClick={() => calNav(-1)} aria-label="Previous">
            <Ic n="chevron-left" s={16} />
          </button>
          <button className="ibtn ibtn-sm" onClick={() => calNav(1)} aria-label="Next">
            <Ic n="chevron-right" s={16} />
          </button>
        </div>
        <h2 style={{ fontSize: 15, fontWeight: 600, margin: "0 4px", letterSpacing: "-.01em" }} aria-live="polite">
          {label}
        </h2>
        <span className="sp" />
        {!project && projs.length > 1 && (
          <span className="row hide-m" style={{ gap: 10, fontSize: 11.5, color: "var(--text-2)", marginRight: 8 }}>
            {projs.slice(0, 5).map((p) => (
              <span key={p!.id} className="row" style={{ gap: 4 }}>
                <span className="pdot" style={css({ "--c": pColor(p) })} />
                {p!.name}
              </span>
            ))}
          </span>
        )}
        <div className="seg">
          {(
            [
              ["month", "Month"],
              ["week", "Week"],
            ] as const
          ).map(([m, n]) => (
            <button key={m} className={mode === m ? "on" : ""} onClick={() => ((S.ui.calMode = m), render())}>
              {n}
            </button>
          ))}
        </div>
      </div>
      {body}
    </div>
  );
}
