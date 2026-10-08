// Gr8r's popovers (gr8r-studio/src/overlays/popovers.js + context-menu.js): one floating menu at a
// time (S.ui.pop), placed under what opened it and kept on screen; Escape or a click outside
// closes it. Picks apply to a task, or to the open New task form ("__form").
import { useEffect, useLayoutEffect, useRef, type CSSProperties, type ReactNode } from "react";

import {
  closePop,
  copy,
  openTask,
  projMove,
  setPref,
  setProjectStatus,
  setRole,
  toggleDone,
  toggleFavProj,
  toggleFavTask,
  updateTask,
} from "../core/actions";
import { LABELS, PRIOS, PSTAT, STATUSES, type ProjectStatusId } from "../core/constants";
import { Ic, WsLogo } from "../core/icons";
import {
  archiveProject,
  archiveTask,
  colAdd,
  colArchive,
  colCollapse,
  colDoneAll,
  colSortPrio,
  copyEmail,
  delFile,
  delProject,
  delTask,
  delView,
  dupFile,
  dupProject,
  dupTask,
  editProject,
  editTask,
  invite,
  newProject,
  newTask,
  newTeam,
  previewFile,
  removeMember,
  renameFile,
  renameView,
  resendInvite,
  resetDemo,
  share,
  shortcuts,
  signOut,
  switchWs,
  toggleOffline,
} from "../core/more";
import { go } from "../core/nav";
import { MOD, MONL, TODAY, WD, addD, dOff, diffD, fmtDate, iso, parse } from "../core/utils";
import { D, S, allTasks, canSee, logAct as logActSub, me, mem, mutate, pColor, proj, render, task, visibleProjects } from "../data/store";
import type { Task } from "../data/types";
import { Av, AvStack, PrIcon, StIcon } from "../ui/helpers";
import { FIELDS, viewChange, viewOf } from "../shell/viewEngine";
import { taskForm } from "./Modals";
import { openPaletteSoon } from "../shell/Shell";

const css = (o: Record<string, string | number>) => o as CSSProperties;
type P = NonNullable<typeof S.ui.pop> & Record<string, unknown>;

/** What a pick changes: the task, or the New task form. */
function target(p: P): (Partial<Task> & Record<string, unknown>) | null {
  if (p.id === "__form") return taskForm() as unknown as Partial<Task> & Record<string, unknown>;
  return (task(p.id as string) as unknown as Partial<Task> & Record<string, unknown>) ?? null;
}
function setField(p: P, patch: Partial<Task>) {
  if (p.id === "__form") {
    Object.assign(taskForm()!, patch);
    render();
    return;
  }
  updateTask(p.id as string, patch);
}

export function startOfWeek(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  const diff = (x.getDay() - S.prefs.weekStart + 7) % 7;
  return addD(x, -diff);
}

interface Item {
  id: string;
  name: string;
  html?: ReactNode;
  on?: boolean;
  kbd?: string | number;
  act?: (id: string) => void;
}
function PopList({ p, items, search, onPick }: { p: P; items: Item[]; search?: string; onPick: (id: string) => void }) {
  const q = String(p.q || "").toLowerCase();
  const list = items.filter((it) => !q || it.name.toLowerCase().includes(q));
  return (
    <>
      {search && (
        <div className="pin">
          <input autoFocus placeholder={search} value={String(p.q || "")} aria-label={search} onChange={(e) => ((p.q = e.target.value), render())} />
        </div>
      )}
      {list.map((it) => (
        <button key={it.id} className="mi" role="menuitemradio" aria-checked={Boolean(it.on)} onClick={() => (it.act ?? onPick)(it.id)}>
          {it.html}
          <span className="trunc">{it.name}</span>
          {it.kbd != null && (
            <span className="r">
              <kbd>{it.kbd}</kbd>
            </span>
          )}
          {it.on && (
            <span className="ck">
              <Ic n="check" s={14} />
            </span>
          )}
        </button>
      ))}
      {!list.length && (
        <div className="mi faint" style={{ cursor: "default" }}>
          No matches
        </div>
      )}
    </>
  );
}

function MiniCal({ p, val, onPick }: { p: P; val: string | null | undefined; onPick: (v: string) => void }) {
  const m = parse(p.m as string)!;
  const start = startOfWeek(new Date(m.getFullYear(), m.getMonth(), 1));
  const cells = Array.from({ length: 42 }, (_, i) => addD(start, i));
  const wdn = Array.from({ length: 7 }, (_, i) => WD[(i + S.prefs.weekStart) % 7]!.slice(0, 2));
  const month = (d: number) => {
    p.m = iso(new Date(m.getFullYear(), m.getMonth() + d, 1));
    render();
  };
  return (
    <div style={{ padding: "6px 6px 2px", width: 252 }}>
      <div className="row" style={{ marginBottom: 6 }}>
        <b style={{ fontWeight: 600, fontSize: 13, paddingLeft: 4 }}>
          {MONL[m.getMonth()]} {m.getFullYear()}
        </b>
        <span className="sp" />
        <button className="ibtn ibtn-xs" onClick={() => month(-1)} aria-label="Previous month">
          <Ic n="chevron-left" s={14} />
        </button>
        <button className="ibtn ibtn-xs" onClick={() => month(1)} aria-label="Next month">
          <Ic n="chevron-right" s={14} />
        </button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 2, textAlign: "center", fontSize: 11 }}>
        {wdn.map((d, i) => (
          <span key={i} className="faint" style={{ padding: "3px 0" }}>
            {d}
          </span>
        ))}
        {cells.map((d) => {
          const ds = iso(d);
          const on = ds === val;
          const today = diffD(d, TODAY) === 0;
          return (
            <button
              key={ds}
              className="num cal-day"
              onClick={() => onPick(ds)}
              aria-label={fmtDate(ds, true)}
              style={{
                height: 30,
                borderRadius: 6,
                fontSize: 12,
                ...(on
                  ? { background: "var(--acc)", color: "var(--on-accent)", fontWeight: 600 }
                  : today
                    ? { color: "var(--acc)", fontWeight: 600, boxShadow: "inset 0 0 0 1px var(--accent-line)" }
                    : d.getMonth() !== m.getMonth()
                      ? { color: "var(--text-3)" }
                      : {}),
              }}
            >
              {d.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Mi({ icon, label, onClick, r, danger }: { icon: string; label: ReactNode; onClick: () => void; r?: ReactNode; danger?: boolean }) {
  return (
    <button className={`mi ${danger ? "danger" : ""}`} onClick={onClick}>
      <Ic n={icon} s={15} />
      {label}
      {r != null && <span className="r">{r}</span>}
    </button>
  );
}
const Sep = () => <div className="msep" />;

function PopInner({ p }: { p: P }): { inner: ReactNode; cls?: string; style?: CSSProperties } | null {
  const t = target(p);
  const pick = (field: string) => (v: string) => {
    let val: string | null = v;
    if (field === "assignee" && !v) val = null;
    if (field === "recur" && v === "Does not repeat") val = null;
    if ((field === "estimate" || field === "due" || field === "start") && !v) val = null;
    S.ui.pop = null;
    const patch: Partial<Task> = { [field]: val } as Partial<Task>;
    if (field === "due" && val && p.id !== "__form" && t?.start && (t.start as string) > val) patch.start = val;
    setField(p, patch);
  };
  switch (p.type) {
    case "create":
      return {
        style: { width: 220 },
        inner: (
          <>
            <div className="mh">Create</div>
            <Mi icon="circle-check" label="Task" onClick={() => newTask()} r={<kbd>N</kbd>} />
            <Mi icon="folder-plus" label="Project" onClick={newProject} r={<kbd>P</kbd>} />
            <Mi icon="users" label="Team" onClick={newTeam} />
            <Mi icon="message-square-plus" label="Chat with the agents" onClick={() => (closePop(), go("chat"))} />
            <Sep />
            <Mi icon="user-plus" label="Invite member" onClick={invite} />
          </>
        ),
      };
    case "subassignee": {
      const tk = task(p.id as string);
      const sb = tk?.subtasks[p.i as number];
      if (!sb) return null;
      return {
        inner: (
          <PopList
            p={p}
            search="Assign subtask to…"
            items={[
              { id: "", name: "Unassigned", html: <Av id={null} cls="sm" tip={false} />, on: !sb.assignee },
              ...D()
                .members.filter((m) => m.status !== "deactivated")
                .map((m) => ({ id: m.id, name: m.name + (m.id === D().me ? " (you)" : ""), html: <Av id={m.id} cls="sm" tip={false} />, on: sb.assignee === m.id })),
            ]}
            onPick={(v) => {
              S.ui.pop = null;
              mutate(() => {
                sb.assignee = v || null;
                logActSub("assigned a subtask on", tk!, v ? `to ${mem(v)!.name}` : "(unassigned)");
              });
            }}
          />
        ),
      };
    }
    case "status":
      return { inner: <PopList p={p} items={STATUSES.map((s, i) => ({ id: s.id, name: s.name, html: <StIcon st={s.id} />, on: t?.status === s.id, kbd: i + 1 }))} onPick={pick("status")} /> };
    case "priority":
      return { inner: <PopList p={p} items={PRIOS.map((x) => ({ id: x.id, name: x.name, html: <PrIcon p={x.id} />, on: t?.priority === x.id }))} onPick={pick("priority")} /> };
    case "assignee":
      return {
        inner: (
          <PopList
            p={p}
            search="Assign to…"
            items={[
              { id: "", name: "Unassigned", html: <Av id={null} cls="sm" tip={false} />, on: !t?.assignee },
              ...D()
                .members.filter((m) => m.status !== "deactivated")
                .map((m) => ({ id: m.id, name: m.name + (m.id === D().me ? " (you)" : ""), html: <Av id={m.id} cls="sm" tip={false} />, on: t?.assignee === m.id })),
              // dotrix: coding tools are assignable; assigning one starts a coding session (with approval)
              { id: "agent:claude-code", name: "Claude Code", html: <Av id="agent:claude-code" cls="sm" tip={false} />, on: t?.assignee === "agent:claude-code" },
              { id: "agent:codex", name: "Codex", html: <Av id="agent:codex" cls="sm" tip={false} />, on: t?.assignee === "agent:codex" },
            ]}
            onPick={pick("assignee")}
          />
        ),
      };
    case "labels":
      return {
        inner: (
          <PopList
            p={p}
            search="Filter labels…"
            items={LABELS.map((l) => ({
              id: l.id,
              name: l.name,
              html: <span className="pdot" style={css({ "--c": l.c })} />,
              on: (t?.labels as string[] | undefined)?.includes(l.id),
            }))}
            onPick={(v) => {
              const cur = (t?.labels as string[]) ?? [];
              setField(p, { labels: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] });
            }}
          />
        ),
      };
    case "project":
      return {
        inner: (
          <PopList
            p={p}
            search="Move to project…"
            items={visibleProjects()
              .filter((q) => canSee(q) && q.status !== "complete")
              .map((q) => ({ id: q.id, name: q.name, html: <span className="pdot" style={css({ "--c": pColor(q) })} />, on: t?.project === q.id }))}
            onPick={pick("project")}
          />
        ),
      };
    case "recur":
      return {
        inner: (
          <PopList
            p={p}
            items={["Does not repeat", "Daily", "Weekly", "Every 2 weeks", "Monthly"].map((x) => ({ id: x, name: x, html: <Ic n="repeat" s={14} />, on: ((t?.recur as string) || "Does not repeat") === x }))}
            onPick={pick("recur")}
          />
        ),
      };
    case "estimate":
      return {
        inner: (
          <PopList
            p={p}
            items={["30m", "1h", "2h", "4h", "1d", "2d", "3d", "5d", "8d"]
              .map((x) => ({ id: x, name: x, html: <Ic n="timer" s={14} />, on: t?.estimate === x }))
              .concat([{ id: "", name: "Clear estimate", html: <Ic n="x" s={14} />, on: false }])}
            onPick={pick("estimate")}
          />
        ),
      };
    case "deps": {
      const tk = task(p.id as string)!;
      const cands = D().tasks.filter((x) => x.project === tk.project && x.id !== tk.id && !x.archived);
      return {
        inner: (
          <PopList
            p={p}
            search="Blocked by…"
            items={cands.map((x) => ({ id: x.id, name: `${x.key}  ${x.title}`, html: <StIcon st={x.status} />, on: tk.deps.includes(x.id) }))}
            onPick={(v) => updateTask(tk.id, { deps: tk.deps.includes(v) ? tk.deps.filter((x) => x !== v) : [...tk.deps, v] })}
          />
        ),
      };
    }
    case "date": {
      const field = p.field as string;
      const tk = task(p.id as string);
      const val = field === "subdue" ? tk?.subtasks[p.i as number]?.due : (t?.[field] as string | null | undefined);
      const onPick = (v: string) => {
        if (field === "subdue") {
          const sb = tk!.subtasks[p.i as number]!;
          S.ui.pop = null;
          mutate(() => {
            sb.due = v || null;
            logActSub("set a subtask due date on", tk!, v ? fmtDate(v) : "(cleared)");
          });
          return;
        }
        pick(field)(v);
      };
      const quick: [string, number][] = [
        ["Today", 0],
        ["Tomorrow", 1],
        ["Next week", 7 - ((TODAY.getDay() + 6) % 7)],
        ["In 2 weeks", 14],
      ];
      return {
        style: { minWidth: 0 },
        inner: (
          <>
            <div className="row" style={{ gap: 4, padding: 4, flexWrap: "wrap" }}>
              {quick.map(([n, d]) => (
                <button key={n} className="badge" style={{ cursor: "pointer" }} onClick={() => onPick(dOff(d))}>
                  {n}
                </button>
              ))}
              {val && (
                <button className="badge" style={{ cursor: "pointer", color: "var(--red)" }} onClick={() => onPick("")}>
                  Clear
                </button>
              )}
            </div>
            <Sep />
            <MiniCal p={p} val={val} onPick={onPick} />
          </>
        ),
      };
    }
    case "pstatus": {
      const pr = proj(p.id as string)!;
      return {
        inner: (
          <PopList
            p={p}
            items={Object.entries(PSTAT).map(([k, v]) => ({ id: k, name: v.name, html: <span className="pdot" style={css({ "--c": v.c, borderRadius: "50%" })} />, on: pr.status === k }))}
            onPick={(v) => setProjectStatus(pr.id, v as ProjectStatusId)}
          />
        ),
      };
    }
    case "role": {
      const m = mem(p.id as string)!;
      const desc: Record<string, string> = {
        Admin: "Manage members, settings, and all projects",
        Member: "Create projects and work on tasks",
        Guest: "Only sees projects they are invited to",
      };
      return {
        style: { width: 300 },
        inner: (
          <>
            <div className="mh">Role for {m.name}</div>
            {["Admin", "Member", "Guest"].map((r) => (
              <button key={r} className="mi" onClick={() => setRole(m.id, r)} style={{ height: "auto", padding: "7px 8px", alignItems: "flex-start" }}>
                <div className="grow" style={{ whiteSpace: "normal" }}>
                  <div style={{ fontWeight: 500 }}>{r}</div>
                  <div className="faint" style={{ fontSize: 11.5 }}>
                    {desc[r]}
                  </div>
                </div>
                {m.role === r && (
                  <span className="ck">
                    <Ic n="check" s={14} />
                  </span>
                )}
              </button>
            ))}
          </>
        ),
      };
    }
    case "ws":
      return {
        style: { width: 260 },
        inner: (
          <>
            <div className="mh">Workspaces</div>
            {D().workspaces.map((w) => (
              <button key={w.id} className="mi" onClick={() => switchWs(w.id)}>
                <WsLogo w={w} px={20} />
                <span className="grow">{w.name}</span>
                <span className="faint" style={{ fontSize: 11 }}>
                  {w.plan}
                </span>
                {w.name === D().ws.name && (
                  <span className="ck">
                    <Ic n="check" s={14} />
                  </span>
                )}
              </button>
            ))}
            <Sep />
            <Mi icon="plus" label="Create workspace" onClick={() => (closePop(), window.location.assign("/onboarding"))} />
            <Mi icon="settings" label="Workspace settings" onClick={() => (closePop(), go("settings", { sec: "workspace" }))} />
            <Mi icon="user-plus" label="Invite members" onClick={invite} />
            <Sep />
            <Mi icon="log-out" label="Sign out" onClick={signOut} />
          </>
        ),
      };
    case "user":
      return {
        style: { width: 260 },
        inner: (
          <>
            <div className="row" style={{ padding: "8px 8px 10px", gap: 10 }}>
              <Av id={D().me} cls="lg" tip={false} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{S.prefs.name}</div>
                <div className="faint trunc" style={{ fontSize: 12 }}>
                  {me().email}
                </div>
              </div>
            </div>
            <Sep />
            <Mi icon="user" label="View profile" onClick={() => (closePop(), go("member", { id: D().me }))} />
            <Mi icon="settings" label="Account settings" onClick={() => (closePop(), go("settings", { sec: "profile" }))} />
            <Sep />
            <div className="mh">Theme</div>
            <div style={{ padding: "2px 6px 6px" }}>
              <div className="seg" style={{ width: "100%" }}>
                {(
                  [
                    ["light", "sun", "Light"],
                    ["dark", "moon", "Dark"],
                    ["system", "monitor", "System"],
                  ] as const
                ).map(([k, i, n]) => (
                  <button key={k} className={S.prefs.theme === k ? "on" : ""} style={{ flex: 1, justifyContent: "center" }} onClick={() => setPref("theme", k)}>
                    <Ic n={i} s={13} />
                    {n}
                  </button>
                ))}
              </div>
            </div>
            <Sep />
            <Mi icon="keyboard" label="Keyboard shortcuts" onClick={shortcuts} r={<kbd>?</kbd>} />
            <Mi icon="log-out" label="Sign out" onClick={signOut} />
          </>
        ),
      };
    case "help":
      return {
        style: { width: 260 },
        inner: (
          <>
            <div className="mh">Help &amp; resources</div>
            <Mi icon="keyboard" label="Keyboard shortcuts" onClick={shortcuts} r={<kbd>?</kbd>} />
            <Mi icon="command" label="Command menu" onClick={() => (closePop(), openPaletteSoon())} r={<kbd>{MOD}K</kbd>} />
            <Mi icon="terminal" label="Connect the CLI" onClick={() => (closePop(), go("settings", { sec: "devices" }))} />
            <Mi icon="component" label="Design system" onClick={() => (closePop(), go("system"))} />
            <Mi icon="layers" label="System states" onClick={() => (closePop(), go("states"))} />
            <Sep />
            <div className="mh">Prototype</div>
            <Mi icon={S.ui.offline ? "wifi" : "wifi-off"} label={S.ui.offline ? "Go back online" : "Simulate offline"} onClick={toggleOffline} />
            <Mi icon="rotate-ccw" label="Reset demo data" onClick={resetDemo} />
          </>
        ),
      };
    case "sort": {
      const k = p.key as string;
      const v = viewOf(k);
      return {
        style: { width: 240 },
        inner: (
          <>
            <div className="mh">Sort by</div>
            {(
              [
                ["manual", "Manual"],
                ["priority", "Priority"],
                ["due", "Due date"],
                ["start", "Start date"],
                ["title", "Title"],
                ["status", "Status"],
                ["assignee", "Assignee"],
                ["created", "Created"],
                ["updated", "Last updated"],
              ] as const
            ).map(([f, n]) => (
              <button key={f} className="mi" onClick={() => viewChange(k, (vv) => ((vv.sort = { f, dir: vv.sort.dir }), (S.ui.pop = null)))}>
                {n}
                {v.sort.f === f && (
                  <span className="ck">
                    <Ic n="check" s={14} />
                  </span>
                )}
              </button>
            ))}
            <Sep />
            <div style={{ padding: "4px 6px" }}>
              <div className="seg" style={{ width: "100%" }}>
                <button className={v.sort.dir > 0 ? "on" : ""} style={{ flex: 1, justifyContent: "center" }} onClick={() => viewChange(k, (vv) => (vv.sort.dir = 1))}>
                  <Ic n="arrow-up" s={12} />
                  Ascending
                </button>
                <button className={v.sort.dir < 0 ? "on" : ""} style={{ flex: 1, justifyContent: "center" }} onClick={() => viewChange(k, (vv) => (vv.sort.dir = -1))}>
                  <Ic n="arrow-down" s={12} />
                  Descending
                </button>
              </div>
            </div>
          </>
        ),
      };
    }
    case "group": {
      const k = p.key as string;
      const v = viewOf(k);
      return {
        inner: (
          <>
            <div className="mh">Group by</div>
            {(
              [
                ["status", "Status", "circle-dot"],
                ["priority", "Priority", "signal-high"],
                ["assignee", "Assignee", "user"],
                ["project", "Project", "folder"],
                ["due", "Due date", "calendar"],
                ["none", "No grouping", "minus"],
              ] as const
            ).map(([g, n, i]) => (
              <button key={g} className="mi" onClick={() => viewChange(k, (vv) => ((vv.group = g), (S.ui.pop = null)))}>
                <Ic n={i} s={15} />
                {n}
                {v.group === g && (
                  <span className="ck">
                    <Ic n="check" s={14} />
                  </span>
                )}
              </button>
            ))}
          </>
        ),
      };
    }
    case "cols": {
      const k = p.key as string;
      const v = viewOf(k);
      return {
        inner: (
          <>
            <div className="mh">Visible columns</div>
            {TCOLS.filter((c) => c[0] !== "title").map((c) => (
              <label key={c[0]} className="mi" style={{ cursor: "pointer" }}>
                <input
                  type="checkbox"
                  className="check"
                  checked={!v.hidden.includes(c[0])}
                  onChange={() => viewChange(k, (vv) => (vv.hidden = vv.hidden.includes(c[0]) ? vv.hidden.filter((x) => x !== c[0]) : [...vv.hidden, c[0]]))}
                />
                {c[1]}
              </label>
            ))}
            <Sep />
            <Mi icon="rotate-ccw" label="Reset widths" onClick={() => viewChange(k, (vv) => (vv.colW = {}))} />
          </>
        ),
      };
    }
    case "filter":
      return { cls: "fbuild", style: { maxWidth: 560 }, inner: <FilterBuilder p={p} /> };
    case "fvals": {
      const k = p.key as string;
      const f = viewOf(k).filters[p.i as number];
      if (!f) return null;
      return {
        inner: (
          <>
            <div className="mh">
              {FIELDS[f.f]!.name} {f.op === "not" ? "is not" : "is"}
            </div>
            {FIELDS[f.f]!.opts().map((o) => (
              <label key={o.id} className="mi" style={{ cursor: "pointer" }}>
                <input type="checkbox" className="check" checked={f.v.includes(o.id)} onChange={() => viewChange(k, () => (f.v = f.v.includes(o.id) ? f.v.filter((x) => x !== o.id) : [...f.v, o.id]))} />
                {o.html}
                {o.name}
              </label>
            ))}
          </>
        ),
      };
    }
    case "daylist": {
      const ds = p.date as string;
      const evs = D().events.filter((e) => e.date === ds);
      const ts = allTasks().filter((x) => x.due === ds);
      return {
        style: { width: 280 },
        inner: (
          <>
            <div className="mh">{fmtDate(ds, true)}</div>
            {evs.map((e) => (
              <button key={e.id} className="mi" onClick={() => (closePop(), go("project", { id: proj(e.project)!.key, tab: "calendar" }))}>
                <Ic n="clock" s={14} />
                {e.title}
                <span className="r">{e.time}</span>
              </button>
            ))}
            {ts.map((x) => (
              <button key={x.id} className="mi" onClick={() => openTask(x.id)}>
                <StIcon st={x.status} />
                <span className="trunc">{x.title}</span>
                <span className="r">
                  <Av id={x.assignee} cls="sm" tip={false} />
                </span>
              </button>
            ))}
          </>
        ),
      };
    }
    case "event": {
      const e = D().events.find((x) => x.id === p.id)!;
      const pr = proj(e.project)!;
      return {
        style: { width: 270 },
        inner: (
          <>
            <div style={{ padding: "10px 10px 6px" }}>
              <div className="row" style={{ gap: 8, marginBottom: 6 }}>
                <span className="pdot" style={css({ "--c": pColor(pr), borderRadius: "50%" })} />
                <b style={{ fontSize: 14, fontWeight: 600 }}>{e.title}</b>
              </div>
              <div className="muted" style={{ fontSize: 12.5, display: "flex", flexDirection: "column", gap: 4 }}>
                <span className="row" style={{ gap: 6 }}>
                  <Ic n="calendar" s={13} />
                  {fmtDate(e.date, true)} · {e.time}
                </span>
                <span className="row" style={{ gap: 6 }}>
                  <Ic n="folder" s={13} />
                  {pr.name}
                </span>
                <span className="row" style={{ gap: 6 }}>
                  <Ic n="users" s={13} />
                  <AvStack ids={pr.members} max={5} />
                </span>
              </div>
            </div>
            <Sep />
            <Mi icon="arrow-up-right" label="Open project" onClick={() => (closePop(), go("project", { id: pr.key, tab: "overview" }))} />
          </>
        ),
      };
    }
    case "emoji":
      return {
        style: { minWidth: 0 },
        inner: (
          <div className="row" style={{ gap: 2, padding: 2 }}>
            {["👍", "🎉", "❤️", "👀", "🚀", "✅"].map((e) => (
              <button key={e} className="ibtn" style={{ fontSize: 16 }} aria-label={`React ${e}`} onClick={() => react(p.id as string, e)}>
                {e}
              </button>
            ))}
          </div>
        ),
      };
    case "ctx":
      return { inner: <CtxMenu p={p} /> };
    case "bulk-status":
    case "bulk-priority":
    case "bulk-assignee":
      return { inner: <BulkMenu p={p} /> };
  }
  return null;
}

/** Comment reactions (yours toggles). */
export function react(commentId: string, e: string) {
  const c = D().comments.find((x) => x.id === commentId);
  if (!c) return;
  S.ui.pop = null;
  mutate(() => {
    const list = c.re[e] || (c.re[e] = []);
    c.re[e] = list.includes(D().me) ? list.filter((x) => x !== D().me) : [...list, D().me];
  });
}

function BulkMenu({ p }: { p: P }) {
  const set = (f: keyof Task, v: string | null) => {
    const ids = [...S.ui.sel];
    S.ui.pop = null;
    mutate(() => ids.forEach((id) => task(id) && Object.assign(task(id)!, { [f]: v, updated: Date.now() })));
  };
  if (p.type === "bulk-status")
    return (
      <>
        {STATUSES.map((s) => (
          <button key={s.id} className="mi" onClick={() => set("status", s.id)}>
            <StIcon st={s.id} />
            {s.name}
          </button>
        ))}
      </>
    );
  if (p.type === "bulk-priority")
    return (
      <>
        {PRIOS.map((s) => (
          <button key={s.id} className="mi" onClick={() => set("priority", s.id)}>
            <PrIcon p={s.id} />
            {s.name}
          </button>
        ))}
      </>
    );
  return (
    <>
      {[{ id: "", name: "Unassigned" }, ...D().members].map((m) => (
        <button key={m.id} className="mi" onClick={() => set("assignee", m.id || null)}>
          <Av id={m.id || null} cls="sm" tip={false} />
          {m.name}
        </button>
      ))}
    </>
  );
}

function CtxMenu({ p }: { p: P }) {
  const id = p.id as string;
  const to = (type: string) => () => {
    S.ui.pop = { ...S.ui.pop!, type, q: "" };
    if (type === "date") S.ui.pop.m = iso(TODAY);
    render();
  };
  if (p.ctx === "task") {
    const t = task(id);
    if (!t) return null;
    return (
      <>
        <Mi icon="panel-right-open" label="Open" onClick={() => openTask(id)} />
        <Mi icon="pencil" label="Edit" onClick={() => editTask(id)} r="E" />
        <Mi icon={t.status === "done" ? "rotate-ccw" : "circle-check"} label={t.status === "done" ? "Reopen" : "Mark complete"} onClick={() => toggleDone(id)} />
        <Sep />
        <Mi icon="circle-dot" label="Status…" onClick={to("status")} />
        <Mi icon="user" label="Assign to…" onClick={to("assignee")} />
        <Mi icon="signal-high" label="Priority…" onClick={to("priority")} />
        <Mi icon="folder-input" label="Move to project…" onClick={to("project")} />
        <Sep />
        <Mi icon="star" label={t.fav ? "Remove from favorites" : "Add to favorites"} onClick={() => toggleFavTask(id)} />
        <Mi icon="link" label="Copy link" onClick={() => (closePop(), void copy(`${location.origin}/w/gr8r/p/${proj(t.project)!.key}/board?task=${t.key}`))} />
        <Mi icon="copy" label="Duplicate" onClick={() => dupTask(id)} />
        <Mi icon="archive" label="Archive" onClick={() => archiveTask(id)} />
        <Sep />
        <Mi icon="trash-2" label="Delete" onClick={() => delTask(id)} r="Del" danger />
      </>
    );
  }
  if (p.ctx === "project") {
    const pr = proj(id);
    if (!pr) return null;
    const vis = visibleProjects();
    return (
      <>
        <Mi icon="arrow-up-right" label="Open" onClick={() => (closePop(), go("project", { id: pr.key }))} />
        <Mi icon="star" label={pr.fav ? "Remove from favorites" : "Add to favorites"} onClick={() => toggleFavProj(id)} />
        <Mi icon="pencil" label="Rename & edit" onClick={() => editProject(id)} />
        <Mi icon="share-2" label="Share" onClick={() => share(id)} />
        <Mi icon="link" label="Copy link" onClick={() => (closePop(), void copy(`${location.origin}/w/gr8r/p/${pr.key}/overview`))} />
        <Mi icon="copy" label="Duplicate" onClick={() => dupProject(id)} />
        <Sep />
        {vis.indexOf(pr) > 0 && <Mi icon="arrow-up" label="Move up in sidebar" onClick={() => projMove(id, -1)} />}
        {vis.indexOf(pr) < vis.length - 1 && <Mi icon="arrow-down" label="Move down in sidebar" onClick={() => projMove(id, 1)} />}
        <Sep />
        <Mi icon="archive" label={pr.status === "complete" ? "Archive" : "Archive project"} onClick={() => archiveProject(id)} />
        <Mi icon="trash-2" label="Delete project" onClick={() => delProject(id)} danger />
      </>
    );
  }
  if (p.ctx === "column") {
    const k = p.key as string;
    return (
      <>
        <div className="mh">{STATUSES.find((s) => s.id === id)?.name}</div>
        <Mi icon="plus" label="Add task" onClick={() => colAdd(k, id)} />
        <Mi icon="fold-horizontal" label="Collapse column" onClick={() => colCollapse(k, id)} />
        {id !== "done" ? <Mi icon="check-check" label="Mark all as done" onClick={() => colDoneAll(k, id)} /> : <Mi icon="archive" label="Archive completed" onClick={() => colArchive(k)} />}
        <Mi icon="arrow-down-wide-narrow" label="Sort by priority" onClick={() => colSortPrio(k, id)} />
      </>
    );
  }
  if (p.ctx === "member") {
    const m = mem(id);
    if (!m) return null;
    const canRm = m.role !== "Owner" && m.id !== D().me;
    return (
      <>
        <Mi icon="user" label="View profile" onClick={() => (closePop(), go("member", { id }))} />
        <Mi icon="plus" label="Assign a task" onClick={() => newTask({ assignee: id })} />
        <Mi icon="mail" label="Copy email" onClick={() => copyEmail(id)} />
        {canRm && (
          <>
            <Mi icon="shield" label="Change role…" onClick={to("role")} />
            {m.status === "invited" && <Mi icon="send" label="Resend invite" onClick={() => resendInvite(id)} />}
            <Sep />
            <Mi icon="user-minus" label="Remove from workspace" onClick={() => removeMember(id)} danger />
          </>
        )}
      </>
    );
  }
  if (p.ctx === "file")
    return (
      <>
        <Mi icon="eye" label="Preview" onClick={() => previewFile(id)} />
        <Mi icon="pencil" label="Rename" onClick={() => renameFile(id)} />
        <Mi icon="link" label="Copy link" onClick={() => (closePop(), void copy(`${location.origin}/w/gr8r/files/${id}`))} />
        <Mi icon="copy" label="Duplicate" onClick={() => dupFile(id)} />
        <Sep />
        <Mi icon="trash-2" label="Delete" onClick={() => delFile(id)} danger />
      </>
    );
  if (p.ctx === "savedview")
    return (
      <>
        <Mi icon="pencil" label="Rename view" onClick={() => renameView(p.vid as string)} />
        <Mi icon="trash-2" label="Delete view" onClick={() => delView(p.vid as string)} danger />
      </>
    );
  return null;
}

function FilterBuilder({ p }: { p: P }) {
  const k = p.key as string;
  const v = viewOf(k);
  return (
    <>
      <div className="mh fb-h">
        Filter by
        {v.filters.length > 0 && (
          <button className="btn btn-sm btn-ghost" onClick={() => viewChange(k, (vv) => (vv.filters = []))}>
            Clear all
          </button>
        )}
      </div>
      {v.filters.length ? (
        <div className="fb-rows">
          {v.filters.map((f, i) => {
            const F = FIELDS[f.f]!;
            const opts = F.opts();
            const names = f.v.map((id) => opts.find((o) => o.id === id)?.name || id);
            const open = p.edit === i;
            return (
              <div key={i}>
                <div className="frow">
                  <span className="conj">{i ? "and" : "Where"}</span>
                  <select className="select" aria-label="Field" value={f.f} onChange={(e) => viewChange(k, () => ((f.f = e.target.value), (f.v = [])))}>
                    {Object.entries(FIELDS).map(([kk, x]) => (
                      <option key={kk} value={kk}>
                        {x.name}
                      </option>
                    ))}
                  </select>
                  <select className="select" aria-label="Operator" value={f.op} onChange={(e) => viewChange(k, () => (f.op = e.target.value as "is" | "not"))}>
                    <option value="is">is</option>
                    <option value="not">is not</option>
                  </select>
                  <button className="valbtn" aria-expanded={open} onClick={() => ((p.edit = open ? undefined : i), render())}>
                    <span className="trunc grow">{names.length ? names.join(", ") : <span className="faint">Select…</span>}</span>
                    <Ic n="chevron-down" s={12} />
                  </button>
                  <button className="ibtn ibtn-xs" aria-label="Remove filter" onClick={() => viewChange(k, (vv) => vv.filters.splice(i, 1))}>
                    <Ic n="trash-2" s={13} />
                  </button>
                </div>
                {open && (
                  <div style={{ marginLeft: 50, border: "1px solid var(--border)", borderRadius: "var(--r)", padding: 4, maxHeight: 200, overflow: "auto" }}>
                    {opts.map((o) => (
                      <label key={o.id} className="mi" style={{ cursor: "pointer", minHeight: 28 }}>
                        <input type="checkbox" className="check" checked={f.v.includes(o.id)} onChange={() => viewChange(k, () => (f.v = f.v.includes(o.id) ? f.v.filter((x) => x !== o.id) : [...f.v, o.id]))} />
                        {o.html}
                        {o.name}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p className="fb-empty">No filters applied. Combine filters to narrow the task list, e.g. Status is In Progress and Assignee is Sarah.</p>
      )}
      <Sep />
      <div className="fb-add">
        <span className="faint">Add filter:</span>
        {Object.entries(FIELDS).map(([kk, x]) => (
          <button
            key={kk}
            className="badge"
            style={{ cursor: "pointer" }}
            onClick={() => viewChange(k, (vv) => (vv.filters.push({ f: kk, op: "is", v: [] }), (p.edit = vv.filters.length - 1)))}
          >
            <Ic n={x.icon} s={11} />
            {x.name}
          </button>
        ))}
      </div>
    </>
  );
}

/** The one floating popover. */
export function PopLayer() {
  const p = S.ui.pop as P | null;
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !p) return;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    let x = p.x as number;
    let y = p.y as number;
    if (x + w > innerWidth - 8) x = Math.max(8, (x as number) + ((p.w as number) || 0) - w);
    if (y + h > innerHeight - 8) y = Math.max(8, ((p.top as number) ?? y) - 4 - h);
    el.style.left = x + "px";
    el.style.top = y + "px";
  });
  useEffect(() => {
    if (!p) return;
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) closePop();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && closePop();
    // after the click that opened it
    const t = setTimeout(() => document.addEventListener("mousedown", down), 0);
    document.addEventListener("keydown", key);
    return () => {
      clearTimeout(t);
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [p]);
  if (!p) return null;
  const out = PopInner({ p });
  if (!out) return null;
  return (
    <div ref={ref} className={`pop floating enter ${out.cls ?? ""}`} role="menu" style={{ left: p.x as number, top: p.y as number, ...out.style }}>
      {out.inner}
    </div>
  );
}

/** The table's columns (views/table): id, name, width. */
export const TCOLS: [string, string, number][] = [
  ["title", "Task", 314],
  ["status", "Status", 132],
  ["priority", "Priority", 112],
  ["assignee", "Assignee", 156],
  ["due", "Due date", 112],
  ["start", "Start date", 112],
  ["labels", "Labels", 180],
  ["deps", "Dependencies", 150],
  ["estimate", "Estimate", 92],
  ["created", "Created", 112],
  ["project", "Project", 156],
];
