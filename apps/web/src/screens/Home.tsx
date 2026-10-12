// Home, with dotrix's "Waiting for a decision": what the
// agents ask you to approve or steer, first in the right column. The workspace's Overview and
// Activity pages folded into this: its stats, workload, and milestones sit here, and the
// activity feed keeps the old filters.
import { useRef, useState, type CSSProperties } from "react";

import { openTask } from "../core/actions";
import { allowed, canInvite } from "../core/can";
import { Ic } from "../core/icons";
import { invite, newProject, newTask } from "../core/more";
import { go } from "../core/nav";
import { DAY, MONL, TODAY, WDL, ago, diffD, fmtDate, greeting, parse, relDate } from "../core/utils";
import { D, S, allTasks, canSee, isOver, pColor, progressOf, proj, render, visibleProjects, who } from "../data/store";
import type { Notif } from "../data/types";
import { STATUSES } from "../core/constants";
import { ActItem, MiniRow } from "../components/TaskList";
import { newThread } from "../core/agents";
import { moodOf } from "../core/presence";
import { isLive } from "../data/live";
import { Face } from "../ui/face";
import { useAtPicker } from "../components/AtPicker";
import { sortTasks, viewOf } from "../shell/viewEngine";
import { Av, AvStack, Empty, PIcon, PStatus, PrIcon, ProgBar } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;

export function goTasks(f: "open" | "done" | "overdue") {
  const v = viewOf("tasks");
  v.filters =
    f === "open"
      ? [{ f: "status", op: "not", v: ["done"] }]
      : f === "done"
        ? [
            { f: "status", op: "is", v: ["done"] },
            { f: "updated", op: "is", v: ["7"] },
          ]
        : [{ f: "due", op: "is", v: ["overdue"] }];
  go("tasks");
}

/** An agent's request in a list (Home, Inbox): who, what, where. */
export function AgentItem({ n }: { n: Notif }) {
  const w = who(n.by);
  const p = n.project ? proj(n.project) : n.task ? proj(D().tasks.find((t) => t.id === n.task)?.project) : null;
  const open = () => (n.thread ? go("chat", {}, { search: `thread=${n.thread}` }) : go("inbox", {}, { search: `n=${n.id}` }));
  return (
    <div className="row" style={{ alignItems: "flex-start", gap: 10, padding: "8px 0", cursor: "pointer" }} onClick={open} role="button" tabIndex={0}>
      <Av id={n.by} cls="md" tip={false} />
      <div className="grow" style={{ fontSize: 13, lineHeight: 1.45, minWidth: 0 }}>
        <div>
          <b style={{ fontWeight: 600 }}>{w?.name}</b> <span className="muted">{n.text}</span>
        </div>
        <div className="trunc muted" style={{ fontSize: 12.5 }}>
          {n.snippet}
        </div>
        <div className="row faint" style={{ gap: 6, marginTop: 3, fontSize: 11.5 }}>
          {p && (
            <>
              <span className="pdot" style={css({ "--c": pColor(p), width: 6, height: 6 })} />
              {p.name}
              <span>·</span>
            </>
          )}
          {ago(n.at)}
        </div>
      </div>
      {n.type === "approval" && <span className="badge amber">Review</span>}
      {n.type === "checkpoint" && <span className="badge accent">Plan</span>}
    </div>
  );
}

const ASKS: [string, string][] = [
  ["file-text", "Summarize what changed this week"],
  ["search", "Research how competitors price their plans"],
  ["list-checks", "Turn the checkout requirements into stories"],
  ["shield-check", "Review what's in review against its acceptance criteria"],
];

/** Home's ask box (after Orbit's): Nova in the middle with the others around it; what you type
 * starts a conversation with Nova, who brings in whoever the work needs. */
function AskHero() {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const lead = D().agents.find((a) => a.handle === "auto") ?? D().agents[0];
  const others = D()
    .agents.filter((a) => a !== lead)
    .slice(0, 5);
  // "@" picks the project the agents read ("" for all of them) and who to ask.
  const ps = visibleProjects().filter((x) => canSee(x) && !x.archived);
  const [pid, setPid] = useState(ps[0]?.id ?? "");
  const [agent, setAgent] = useState(lead?.handle ?? "auto");
  const ag = D().agents.find((a) => a.handle === agent) ?? lead;
  const projects: [string, string][] = [...ps.map((p): [string, string] => [p.id, p.name]), ["", "All projects"]];
  const at = useAtPicker({ text, setText, ref, projects, project: pid, onProject: setPid, agent, onAgent: setAgent });
  const ask = (q: string) => {
    const t = q.trim();
    if (!t) return;
    // A real workspace's chat isn't wired yet: the question waits in a new chat there.
    if (isLive()) {
      const where = pid ? `project=${proj(pid)?.key}` : "across=1";
      return go("chat", {}, { search: `new=1&${where}&agent=${agent}&q=${encodeURIComponent(t)}` });
    }
    const th = newThread(pid || null, agent, S.ui.chatModel, t, pid ? undefined : ps.map((x) => x.id));
    if (th) go("chat", {}, { search: `thread=${th.id}` });
  };
  return (
    <section className="ask-hero" aria-label={`Ask ${lead?.name ?? "the agents"}`}>
      <div className="ask-orbit" aria-hidden>
        {lead && (
          <span className="lead">
            <Face c={lead.c} size={64} mood={moodOf(lead.handle)} />
          </span>
        )}
        {others.map((a, i) => (
          <span key={a.handle} className={`sat s${i}`} style={{ "--c": a.c } as CSSProperties}>
            <Face c={a.c} size={24} mood={moodOf(a.handle)} />
            <em>{a.name}</em>
          </span>
        ))}
      </div>
      <div className="ask-wrap">
        <form
          className="cbox ask-box"
          onSubmit={(e) => {
            e.preventDefault();
            ask(text);
          }}
        >
          <textarea
            ref={ref}
            rows={2}
            value={text}
            placeholder={`Ask ${ag?.name ?? "the agents"} anything, or type @ to pick a project or an agent`}
            onChange={(e) => at.onChange(e.target)}
            onKeyDown={(e) => {
              if (at.onKeyDown(e)) return;
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask(text);
              }
            }}
            aria-label={`Ask ${ag?.name ?? "the agents"}`}
            aria-expanded={at.open}
          />
          <div className="cbox-row">
            <button type="button" className="cpill pick" onClick={at.start} data-tip="Type @ to pick another project">
              <Ic n={pid ? "at-sign" : "layers"} s={12} />
              <span className="trunc">{projects.find(([v]) => v === pid)?.[1]}</span>
            </button>
            <button type="button" className="cpill pick" onClick={at.start} data-tip="Type @ to ask another agent">
              {ag && <Face c={ag.c} size={16} mood="idle" />}
              {ag?.name} · {ag?.role}
            </button>
            <span className="sp" />
            <span className="faint hide-m" style={{ fontSize: 11 }}>
              ↵ to start
            </span>
            <button className="cbox-send" type="submit" disabled={!text.trim()} aria-label="Start">
              <Ic n="arrow-up" s={14} />
            </button>
          </div>
        </form>
        {at.menu}
      </div>
      <div className="ask-sugg">
        {ASKS.map(([i, q]) => (
          <button key={q} className="cpill pick" onClick={() => ask(q)}>
            <Ic n={i} s={12} />
            {q}
          </button>
        ))}
      </div>
    </section>
  );
}

export function Home() {
  const [tab, setTab] = useState<"upcoming" | "overdue" | "completed">("upcoming");
  const all = allTasks();
  const mineAll = all.filter((t) => t.assignee === D().me);
  const activeP = visibleProjects().filter((p) => canSee(p) && p.status !== "complete");
  const open = all.filter((t) => t.status !== "done");
  const doneWk = all.filter((t) => t.status === "done" && t.completedAt && Date.now() - t.completedAt < 7 * DAY);
  const over = all.filter(isOver);
  const lists = {
    upcoming: sortTasks(
      mineAll.filter((t) => t.status !== "done" && !isOver(t)),
      { f: "due", dir: 1 },
    ),
    overdue: mineAll.filter(isOver),
    completed: sortTasks(
      mineAll.filter((t) => t.status === "done"),
      { f: "updated", dir: 1 },
    ),
  };
  const cur = lists[tab].slice(0, 7);
  const dl = (lab: string, a: number, b: number) => ({
    lab,
    ts: sortTasks(
      open.filter((t) => t.due && diffD(parse(t.due)!, TODAY) >= a && diffD(parse(t.due)!, TODAY) <= b),
      { f: "priority", dir: 1 },
    ),
  });
  const dls = [dl("Today", 0, 0), dl("Tomorrow", 1, 1), dl("This week", 2, 7)];
  const waiting = D().notifs.filter((n) => (n.type === "approval" || n.type === "checkpoint") && !n.read);
  // From the old workspace Overview: what the agents did, and how the work is spread.
  const agentActs = D().activity.filter((a) => !D().members.some((m) => m.id === a.by)).length;
  const tokens = D()
    .threads.flatMap((t) => t.messages)
    .reduce((sum, m) => sum + (m.tokens ?? 0), 0);
  const load = D()
    .members.filter((m) => m.status === "active")
    .map((m) => ({ m, ts: all.filter((t) => t.assignee === m.id && t.status !== "done") }))
    .sort((a, b) => b.ts.length - a.ts.length)
    .filter((l) => l.ts.length > 0)
    .slice(0, 8);
  const maxL = Math.max(...load.map((l) => l.ts.length), 1);
  const ms = activeP
    .flatMap((p) => (p.milestones || []).map((m) => ({ ...m, p })))
    .filter((m) => diffD(parse(m.date)!, TODAY) >= 0)
    .sort((a, b) => (a.date > b.date ? 1 : -1))
    .slice(0, 4);
  // From the old workspace Activity page: the same filters on the same feed.
  const actF = S.ui.actFilter;
  const actWho = S.ui.actWho;
  let acts = D().activity.filter((a) => !a.project || canSee(proj(a.project)));
  if (actF !== "all")
    acts = acts.filter((a) =>
      actF === "comments"
        ? a.verb.includes("comment")
        : actF === "status"
          ? /moved|completed|reopened/.test(a.verb)
          : actF === "projects"
            ? a.verb.includes("project")
            : actF === "agents"
              ? !D().members.some((m) => m.id === a.by)
              : true,
    );
  if (actWho !== "all") acts = acts.filter((a) => a.by === actWho);
  return (
    <div className="page">
      <div className="ph">
        <div>
          <h1>
            {greeting()}, {S.prefs.name.split(" ")[0]}
          </h1>
          <p>
            <span className="num">
              {WDL[TODAY.getDay()]}, {MONL[TODAY.getMonth()]} {TODAY.getDate()}
            </span>{" "}
            · Here&apos;s what&apos;s happening across your workspace.
          </p>
        </div>
        <div className="acts">
          {canInvite() && (
            <button className="btn btn-secondary hide-m" onClick={invite}>
              <Ic n="user-plus" s={14} />
              Invite member
            </button>
          )}
          {allowed("projects:manage") && (
            <button className="btn btn-secondary hide-m" onClick={newProject}>
              <Ic n="folder-plus" s={14} />
              New project
            </button>
          )}
          <button className="btn btn-primary" onClick={() => newTask()}>
            <Ic n="plus" s={14} />
            New task
          </button>
        </div>
      </div>
      <AskHero />
      <div className="stats" style={{ marginBottom: 16 }}>
        <button className="stat" onClick={() => go("projects")}>
          <span className="k">
            <Ic n="folder-kanban" s={14} />
            Active projects
          </span>
          <span className="v">{activeP.length}</span>
          <span className="d">{activeP.filter((p) => p.status === "risk").length} at risk</span>
        </button>
        <button className="stat" onClick={() => goTasks("open")}>
          <span className="k">
            <Ic n="circle-dashed" s={14} />
            Open tasks
          </span>
          <span className="v">{open.length}</span>
          <span className="d">{open.filter((t) => t.assignee === D().me).length} assigned to you</span>
        </button>
        <button className="stat" onClick={() => goTasks("done")}>
          <span className="k">
            <Ic n="circle-check" s={14} />
            Completed
          </span>
          <span className="v">{doneWk.length}</span>
          <span className="d up">this week</span>
        </button>
        <button className="stat" onClick={() => goTasks("overdue")}>
          <span className="k">
            <Ic n="clock-alert" s={14} />
            Overdue
          </span>
          <span className="v" style={over.length ? { color: "var(--red)" } : undefined}>
            {over.length}
          </span>
          <span className={`d ${over.length ? "bad" : ""}`}>{over.length ? "need attention" : "all on track"}</span>
        </button>
        <button className="stat" onClick={() => ((S.ui.actFilter = "agents"), render(), document.getElementById("h-activity")?.scrollIntoView())}>
          <span className="k">
            <Ic n="sparkles" s={14} />
            Agents this week
          </span>
          <span className="v">{agentActs}</span>
          <span className="d">{Math.round(tokens / 1000)}k tokens</span>
        </button>
      </div>
      <div className="grid2">
        <div className="stack">
          <section className="panel" aria-labelledby="h-mytasks">
            <div className="panel-h">
              <h2 id="h-mytasks">My tasks</h2>
              <div className="acts">
                <div className="seg" role="tablist">
                  {(
                    [
                      ["upcoming", "Upcoming"],
                      ["overdue", "Overdue"],
                      ["completed", "Completed"],
                    ] as const
                  ).map(([k, n]) => (
                    <button key={k} role="tab" className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
                      {n} <span className="faint">{lists[k].length}</span>
                    </button>
                  ))}
                </div>
                <button className="ibtn ibtn-sm" onClick={() => go("mytasks")} data-tip="Open My Tasks" aria-label="Open My Tasks">
                  <Ic n="arrow-up-right" s={15} />
                </button>
              </div>
            </div>
            {cur.length ? (
              cur.map((t) => <MiniRow key={t.id} t={t} av={false} />)
            ) : (
              <Empty
                icon={tab === "overdue" ? "circle-check" : "list-checks"}
                title={tab === "overdue" ? "Nothing overdue" : "No tasks here"}
                text={tab === "overdue" ? "Every task assigned to you is on schedule." : "Add a task to get things moving."}
                cls="sm"
              />
            )}
            {lists[tab].length > 7 && (
              <button className="addrow" style={{ paddingLeft: 14, borderTop: "1px solid var(--divider)", borderBottom: 0 }} onClick={() => go("mytasks")}>
                View all {lists[tab].length} tasks <Ic n="arrow-right" s={13} />
              </button>
            )}
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Project progress</h2>
              <div className="acts">
                <button className="btn btn-sm btn-ghost" onClick={() => go("projects")}>
                  All projects
                </button>
              </div>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="perm-t" style={{ minWidth: 560 }}>
                <thead>
                  <tr>
                    <th style={{ paddingLeft: 14 }}>Project</th>
                    <th style={{ textAlign: "left" }}>Status</th>
                    <th style={{ textAlign: "left", width: "26%" }}>Progress</th>
                    <th style={{ textAlign: "left" }}>Due</th>
                    <th style={{ textAlign: "right", paddingRight: 14 }}>Team</th>
                  </tr>
                </thead>
                <tbody>
                  {activeP.map((p) => {
                    const pr = progressOf(p.id);
                    return (
                      <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => go("project", { id: p.key, tab: "overview" })}>
                        <td style={{ paddingLeft: 14 }}>
                          <span className="row">
                            <PIcon p={p} s={14} />
                            <b style={{ fontWeight: 500 }}>{p.name}</b>
                          </span>
                        </td>
                        <td style={{ textAlign: "left" }}>
                          <PStatus s={p.status} />
                        </td>
                        <td>
                          <span className="row">
                            <ProgBar v={pr} cls={p.status === "risk" ? "red" : ""} />
                            <span className="num faint" style={{ fontSize: 11.5, width: 30 }}>
                              {pr}%
                            </span>
                          </span>
                        </td>
                        <td style={{ textAlign: "left" }} className="num muted">
                          {fmtDate(p.due)}
                        </td>
                        <td style={{ textAlign: "right", paddingRight: 14 }}>
                          <AvStack ids={p.members} max={3} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </div>
        <div className="stack">
          {waiting.length > 0 && (
            <section className="panel">
              <div className="panel-h">
                <h2>Waiting for a decision</h2>
                <span className="badge amber">{waiting.length}</span>
                <div className="acts">
                  <button className="btn btn-sm btn-ghost" onClick={() => go("inbox", {}, { search: "tab=needs" })}>
                    View all
                  </button>
                </div>
              </div>
              <div className="panel-b" style={{ paddingBottom: 6 }}>
                {waiting.slice(0, 3).map((n) => (
                  <AgentItem key={n.id} n={n} />
                ))}
              </div>
            </section>
          )}
          <section className="panel">
            <div className="panel-h">
              <h2>Upcoming deadlines</h2>
            </div>
            <div className="panel-b" style={{ paddingBottom: 6 }}>
              {ms.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div className="row" style={{ fontSize: 11.5, fontWeight: 600, color: "var(--text-2)", marginBottom: 4 }}>
                    Milestones
                    <span className="faint" style={{ fontWeight: 500 }}>
                      {ms.length}
                    </span>
                  </div>
                  {ms.map((m) => (
                    <div
                      key={m.p.id + m.name}
                      className="row"
                      style={{ height: 30, cursor: "pointer", gap: 8, fontSize: 13 }}
                      onClick={() => go("project", { id: m.p.key, tab: "timeline" })}
                    >
                      <span
                        style={{ width: 9, height: 9, transform: "rotate(45deg)", background: pColor(m.p), borderRadius: 2, flexShrink: 0, margin: "0 3px" }}
                      />
                      <span className="trunc grow">
                        {m.name} <span className="faint">· {m.p.name}</span>
                      </span>
                      <span className="num muted">{relDate(m.date)}</span>
                    </div>
                  ))}
                </div>
              )}
              {dls.map((g) => (
                <div key={g.lab} style={{ marginBottom: 10 }}>
                  <div className="row" style={{ fontSize: 11.5, fontWeight: 600, color: "var(--text-2)", marginBottom: 4 }}>
                    {g.lab}
                    <span className="faint" style={{ fontWeight: 500 }}>
                      {g.ts.length}
                    </span>
                  </div>
                  {g.ts.length ? (
                    <>
                      {g.ts.slice(0, 4).map((t) => (
                        <div key={t.id} className="row" style={{ height: 30, cursor: "pointer", gap: 8, fontSize: 13 }} onClick={() => openTask(t.id)}>
                          <span className="pdot" style={css({ "--c": pColor(proj(t.project)) })} />
                          <span className="trunc grow">{t.title}</span>
                          <PrIcon p={t.priority} s={13} />
                          <Av id={t.assignee} cls="sm" />
                        </div>
                      ))}
                      {g.ts.length > 4 && (
                        <div className="faint" style={{ fontSize: 11.5, paddingLeft: 16 }}>
                          +{g.ts.length - 4} more
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="faint" style={{ fontSize: 12.5, padding: "4px 0 2px" }}>
                      Nothing due
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
          <section className="panel" aria-labelledby="h-activity">
            <div className="panel-h" style={{ flexWrap: "wrap", gap: 8 }}>
              <h2 id="h-activity">Activity</h2>
              <div className="seg" style={{ marginLeft: "auto" }}>
                {(
                  [
                    ["all", "All"],
                    ["status", "Status"],
                    ["comments", "Comments"],
                    ["projects", "Projects"],
                    ["agents", "Agents"],
                  ] as const
                ).map(([k, n]) => (
                  <button key={k} className={actF === k ? "on" : ""} onClick={() => ((S.ui.actFilter = k), render())}>
                    {n}
                  </button>
                ))}
              </div>
              <select
                className="select"
                style={{ height: 26, width: "auto", fontSize: 12 }}
                value={actWho}
                onChange={(e) => ((S.ui.actWho = e.target.value), render())}
                aria-label="Filter by person"
              >
                <option value="all">Everyone</option>
                {D().members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="panel-b feed lined">
              {acts.length ? (
                acts.slice(0, 10).map((a) => <ActItem key={a.id} a={a} withProject />)
              ) : (
                <Empty icon="activity" title="Nothing here" text="No activity matches these filters." cls="sm" />
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Workload</h2>
              <div className="acts">
                <span className="faint" style={{ fontSize: 11.5 }}>
                  Open tasks per person
                </span>
              </div>
            </div>
            <div className="panel-b">
              {load.map((l) => (
                <div key={l.m.id} className="row" style={{ height: 30, fontSize: 13, cursor: "pointer" }} onClick={() => go("member", { id: l.m.id })}>
                  <Av id={l.m.id} cls="sm" tip={false} />
                  <span style={{ width: 96 }} className="trunc">
                    {l.m.name.split(" ")[0]}
                  </span>
                  <span className="grow" style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--surface-3)" }}>
                    <span style={{ display: "flex", width: `${(l.ts.length / maxL) * 100}%` }}>
                      {STATUSES.filter((st) => st.id !== "done").map((st) => {
                        const n = l.ts.filter((t) => t.status === st.id).length;
                        return n ? <i key={st.id} style={{ display: "block", flex: n, background: `var(--st-${st.id})` }} /> : null;
                      })}
                    </span>
                  </span>
                  <span className="num muted" style={{ width: 22, textAlign: "right" }}>
                    {l.ts.length}
                  </span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
