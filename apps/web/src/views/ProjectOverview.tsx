// Gr8r's project overview and activity (gr8r-studio/src/views/project-overview.js). dotrix adds
// "Ask in Chat" for a summary, and the agents' latest conversations about the project.
import type { CSSProperties } from "react";

import { openPop } from "../core/actions";
import { STATUSES } from "../core/constants";
import { Ic } from "../core/icons";
import { editProject, share } from "../core/more";
import { go } from "../core/nav";
import { TODAY, ago, dayBucket, diffD, fmtDate, parse } from "../core/utils";
import { D, TM, isOver, mem, pColor, progressOf, task, tasksOf } from "../data/store";
import type { Activity, Project } from "../data/types";
import { ActItem, MiniRow } from "../components/TaskList";
import { sortTasks, viewOf } from "../shell/viewEngine";
import { Av, AvStack, Empty, PStatus, StIcon } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;

function goFilteredList(p: Project, st: string) {
  const v = viewOf("p:" + p.id);
  v.filters = [{ f: "status", op: "is", v: [st] }];
  v.group = "status";
  go("project", { id: p.key, tab: "list" });
}

export function ProjectOverview({ p }: { p: Project }) {
  const ts = tasksOf(p.id);
  const pr = progressOf(p.id);
  const cnt = STATUSES.map((s) => ({ s, n: ts.filter((t) => t.status === s.id).length }));
  const over = ts.filter(isOver);
  const soon = sortTasks(
    ts.filter((t) => t.status !== "done" && t.due),
    { f: "due", dir: 1 },
  ).slice(0, 6);
  const acts = D()
    .activity.filter((a) => a.project === p.id)
    .slice(0, 6);
  const daysLeft = p.due ? diffD(parse(p.due)!, TODAY) : null;
  const threads = D()
    .threads.filter((t) => t.project === p.id)
    .slice(0, 3);
  return (
    <div className="page" style={{ maxWidth: 1160, paddingTop: 22 }}>
      <div className="grid2">
        <div className="stack">
          <section className="panel">
            <div className="panel-h">
              <h2>About</h2>
              <div className="acts">
                <button className="btn btn-sm btn-ghost" onClick={() => editProject(p.id)}>
                  <Ic n="pencil" s={13} />
                  Edit
                </button>
              </div>
            </div>
            <div className="panel-b" style={{ fontSize: 14, lineHeight: 1.6, color: "var(--text)" }}>
              {p.desc}
            </div>
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Progress</h2>
              <div className="acts">
                <span className="faint" style={{ fontSize: 12 }}>
                  {ts.filter((t) => t.status === "done").length} of {ts.length} tasks done
                </span>
              </div>
            </div>
            <div className="panel-b">
              <div className="row" style={{ alignItems: "baseline", gap: 10, marginBottom: 10 }}>
                <span style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-.03em" }} className="num">
                  {pr}%
                </span>
                <span className="muted">
                  {daysLeft === null ? "No target date" : daysLeft >= 0 ? `${daysLeft} days until ${fmtDate(p.due)}` : `Ended ${fmtDate(p.due)}`}
                </span>
                {over.length > 0 && (
                  <span className="badge red">
                    <Ic n="clock-alert" s={11} />
                    {over.length} overdue
                  </span>
                )}
              </div>
              <div className="stackbar" style={{ height: 8, marginBottom: 12 }}>
                {cnt.map((c) => (
                  <i
                    key={c.s.id}
                    style={{ width: `${(c.n / Math.max(ts.length, 1)) * 100}%`, background: `var(--st-${c.s.id})` }}
                    title={`${c.s.name}: ${c.n}`}
                  />
                ))}
              </div>
              <div className="row" style={{ flexWrap: "wrap", gap: 14, fontSize: 12.5 }}>
                {cnt.map((c) => (
                  <button key={c.s.id} className="row" style={{ gap: 5 }} onClick={() => goFilteredList(p, c.s.id)}>
                    <StIcon st={c.s.id} s={12} />
                    <span className="muted">{c.s.name}</span>
                    <b className="num" style={{ fontWeight: 600 }}>
                      {c.n}
                    </b>
                  </button>
                ))}
              </div>
            </div>
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Coming up</h2>
              <div className="acts">
                <button className="btn btn-sm btn-ghost" onClick={() => go("project", { id: p.key, tab: "list" })}>
                  View list
                </button>
              </div>
            </div>
            {soon.length ? (
              soon.map((t) => <MiniRow key={t.id} t={t} noProj />)
            ) : (
              <Empty icon="circle-check" title="Nothing scheduled" text="Tasks with due dates will show up here." cls="sm" />
            )}
          </section>
        </div>
        <div className="stack">
          <section className="panel">
            <div className="panel-h">
              <h2>Details</h2>
            </div>
            <div className="panel-b">
              <dl className="kv">
                <dt>
                  <Ic n="circle-dot" s={14} />
                  Status
                </dt>
                <dd>
                  <button className="pillbtn" onClick={(e) => openPop(e.currentTarget, "pstatus", { id: p.id })}>
                    <PStatus s={p.status} />
                  </button>
                </dd>
                <dt>
                  <Ic n="user" s={14} />
                  Lead
                </dt>
                <dd>
                  <span className="pillbtn">
                    <Av id={p.lead} cls="sm" tip={false} />
                    {mem(p.lead)?.name}
                  </span>
                </dd>
                <dt>
                  <Ic n="users" s={14} />
                  Team
                </dt>
                <dd>
                  <button className="pillbtn" onClick={() => go("team", { id: p.team })}>
                    <Ic n={TM(p.team).icon} s={13} />
                    {TM(p.team).name}
                  </button>
                </dd>
                <dt>
                  <Ic n="calendar" s={14} />
                  Start
                </dt>
                <dd>
                  <span className="pillbtn num">{fmtDate(p.start, true)}</span>
                </dd>
                <dt>
                  <Ic n="flag" s={14} />
                  Due
                </dt>
                <dd>
                  <span className="pillbtn num">{fmtDate(p.due, true)}</span>
                </dd>
                <dt>
                  <Ic n="user-plus" s={14} />
                  Members
                </dt>
                <dd>
                  <button className="pillbtn" onClick={() => share(p.id)}>
                    <AvStack ids={p.members} max={6} />
                    <span className="faint">{p.members.length}</span>
                  </button>
                </dd>
              </dl>
            </div>
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Ask the agents</h2>
              <div className="acts">
                <button className="btn btn-sm btn-secondary" onClick={() => go("chat", {}, { search: `project=${p.key}` })}>
                  <Ic n="message-square" s={13} />
                  Ask in Chat
                </button>
              </div>
            </div>
            <div className="panel-b">
              {threads.length ? (
                threads.map((t) => (
                  <div
                    key={t.id}
                    className="row"
                    style={{ height: 32, fontSize: 13, cursor: "pointer" }}
                    onClick={() => go("chat", {}, { search: `thread=${t.id}` })}
                  >
                    <Ic n="message-square" s={13} />
                    <span className="grow trunc">{t.title}</span>
                    <span className="faint" style={{ fontSize: 11.5 }}>
                      {ago(t.at)}
                    </span>
                  </div>
                ))
              ) : (
                <span className="faint">Ask for a summary of what changed, what&apos;s blocked, and what&apos;s due.</span>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Milestones</h2>
            </div>
            <div className="panel-b">
              {(p.milestones || []).length ? (
                p.milestones.map((m) => {
                  const n = diffD(parse(m.date)!, TODAY);
                  return (
                    <div key={m.name} className="row" style={{ height: 32, fontSize: 13 }}>
                      <span
                        style={{
                          width: 9,
                          height: 9,
                          transform: "rotate(45deg)",
                          borderRadius: 2,
                          flexShrink: 0,
                          margin: "0 3px",
                          background: n < 0 ? "var(--green)" : pColor(p),
                        }}
                      />
                      <span className={`grow trunc ${n < 0 ? "faint" : ""}`}>{m.name}</span>
                      <span className="num muted">{fmtDate(m.date)}</span>
                    </div>
                  );
                })
              ) : (
                <span className="faint">No milestones yet</span>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Recent activity</h2>
              <div className="acts">
                <button className="btn btn-sm btn-ghost" onClick={() => go("project", { id: p.key, tab: "activity" })}>
                  View all
                </button>
              </div>
            </div>
            <div className="panel-b feed">{acts.length ? acts.map((a) => <ActItem key={a.id} a={a} />) : <span className="faint">No activity yet</span>}</div>
          </section>
        </div>
      </div>
    </div>
  );
}

export function ProjectActivity({ p }: { p: Project }) {
  const as = D().activity.filter((a) => a.project === p.id);
  const cs: Activity[] = D()
    .comments.filter((c) => task(c.task)?.project === p.id)
    .map((c) => ({ id: c.id, by: c.by, verb: "commented on", task: c.task, project: p.id, at: c.at, extra: "" }));
  const all = [...as, ...cs].sort((a, b) => b.at - a.at);
  const b: Record<string, Activity[]> = {};
  all.forEach((a) => (b[dayBucket(a.at)] ||= []).push(a));
  return (
    <div className="page" style={{ maxWidth: 780, paddingTop: 18 }}>
      {all.length ? (
        Object.entries(b).map(([k, list]) => (
          <div key={k}>
            <div className="day-h">{k}</div>
            <div className="feed lined">
              {list.map((a) => (
                <ActItem key={a.id} a={a} />
              ))}
            </div>
          </div>
        ))
      ) : (
        <Empty icon="activity" title="No activity yet" text="Changes to this project will appear here." />
      )}
    </div>
  );
}

export { css };
