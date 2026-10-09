// Gr8r's members, teams, and profiles (gr8r-studio/src/pages/members.js). dotrix's roles table
// adds what each role may do with the agents (approving changes, editing documents, coding).
import { openPop } from "../core/actions";
import { ROLES } from "../core/constants";
import { allowed, canInvite } from "../core/can";
import { Ic } from "../core/icons";
import { copyEmail, editTeam, invite, newTask, newTeam } from "../core/more";
import { go, useRoute } from "../core/nav";
import { ago, minsAgo } from "../core/utils";
import { D, S, TM, allTasks, canSee, isOver, me, mem, progressOf, render, team, teamsList, visibleProjects } from "../data/store";
import { ActItem, MiniRow } from "../components/TaskList";
import { sortTasks } from "../shell/viewEngine";
import { Av, AvStack, Empty, PIcon, PStatus, ProgBar } from "../ui/helpers";

const set = (k: "memQ" | "memRole" | "membersTab" | "memTab", v: string) => ((S.ui[k] = v), render());
const ctx = (id: string) => (e: React.MouseEvent<HTMLElement>) => {
  e.preventDefault();
  e.stopPropagation();
  openPop(e.currentTarget, "ctx", { ctx: "member", id, x: e.type === "contextmenu" ? e.clientX : undefined, y: e.type === "contextmenu" ? e.clientY : undefined });
};

function NotFound() {
  return (
    <div className="page">
      <Empty icon="file-question" title="Page not found" text="The page you're looking for doesn't exist or was moved.">
        <button className="btn btn-secondary btn-sm" onClick={() => go("members")}>
          Back to members
        </button>
      </Empty>
    </div>
  );
}

// [what, Owner, Admin, Member, Guest]; "grant" = off by default, a workspace can grant it to members
const PERMS: [string, ...(0 | 1 | "grant")[]][] = [
  ["View projects & tasks", 1, 1, 1, 1],
  ["Comment on tasks", 1, 1, 1, 1],
  ["Create and edit tasks", 1, 1, 1, 0],
  ["Chat with the agents", 1, 1, 1, 0],
  ["Edit documents (Knowledge)", 1, 1, "grant", 0],
  ["Approve agents' changes", 1, 1, "grant", 0],
  ["Start coding on a task", 1, 1, "grant", 0],
  ["Choose the agents' model", 1, 1, "grant", 0],
  ["Create projects", 1, 1, 0, 0],
  ["Invite members", 1, 1, 0, 0],
  ["Manage roles", 1, 1, 0, 0],
  ["Configure agents, rules, automations", 1, 1, 0, 0],
  ["Workspace settings and audit log", 1, 1, 0, 0],
  ["Billing", 1, 0, 0, 0],
  ["Delete workspace", 1, 0, 0, 0],
];
export function PermsTable() {
  return (
    <div className="panel" style={{ overflowX: "auto" }}>
      <table className="perm-t" style={{ minWidth: 560 }}>
        <thead>
          <tr>
            <th style={{ paddingLeft: 14 }}>Permission</th>
            {ROLES.map((r) => (
              <th key={r}>{r}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {PERMS.map(([what, ...vals]) => (
            <tr key={what}>
              <td style={{ paddingLeft: 14 }}>{what}</td>
              {vals.map((v, i) => (
                <td key={i}>
                  {v === "grant" ? (
                    <span className="badge" data-tip="Off by default; Settings → What members can do">
                      Optional
                    </span>
                  ) : v ? (
                    <span style={{ color: "var(--green)", display: "inline-flex" }} aria-label="Allowed">
                      <Ic n="check" s={15} />
                    </span>
                  ) : (
                    <span className="faint" style={{ display: "inline-flex" }} aria-label="Not allowed">
                      <Ic n="minus" s={15} />
                    </span>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TeamsGrid() {
  return (
    <div className="pgrid">
      {teamsList().map((t) => {
        const ms = D().members.filter((m) => m.team === t.id);
        const ps = visibleProjects().filter((p) => p.team === t.id);
        return (
          <div key={t.id} className="pcard" onClick={() => go("team", { id: t.id })} role="link" tabIndex={0}>
            <div className="row">
              <span className="picon" style={{ "--c": t.c } as React.CSSProperties}>
                <Ic n={t.icon} s={15} />
              </span>
              <b style={{ fontWeight: 600, fontSize: 14 }}>{t.name}</b>
            </div>
            <div className="desc">{t.desc}</div>
            <div className="foot">
              <span className="row" style={{ gap: 4 }}>
                <Ic n="users" s={12} />
                {ms.length} members
              </span>
              <span className="row" style={{ gap: 4 }}>
                <Ic n="folder" s={12} />
                {ps.length} projects
              </span>
              <span className="sp" />
              <AvStack ids={ms.map((m) => m.id)} max={4} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Members() {
  const u = S.ui;
  const q = (u.memQ || "").toLowerCase();
  const role = u.memRole || "all";
  const ms = D().members.filter((m) => (role === "all" || m.role === role) && (!q || m.name.toLowerCase().includes(q) || m.email.includes(q)));
  const isAdmin = ["Owner", "Admin"].includes(me()!.role);
  const tab = u.membersTab;
  return (
    <div className="page wide" style={{ maxWidth: 1200 }}>
      <div className="ph">
        <div>
          <h1>Members</h1>
          <p>
            {D().members.length} people in {D().ws.name} · {D().members.filter((m) => m.status === "invited").length} pending
          </p>
        </div>
        <div className="acts">
          {canInvite() && (<button className="btn btn-primary" onClick={invite}>
            <Ic n="user-plus" s={14} />
            Invite member
          </button>)}
        </div>
      </div>
      <div className="tabs" style={{ marginBottom: 14 }}>
        {[
          ["members", "Members"],
          ["teams", "Teams"],
          ["roles", "Roles & permissions"],
        ].map(([k, n]) => (
          <button key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => set("membersTab", k!)}>
            {n}
          </button>
        ))}
      </div>
      {tab === "teams" ? (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <span className="muted" style={{ fontSize: 13 }}>
              {teamsList().length} teams
            </span>
            <span className="sp" />
            {allowed("members:manage") && (<button className="btn btn-secondary btn-sm" onClick={newTeam}>
              <Ic n="plus" s={13} />
              New team
            </button>)}
          </div>
          <TeamsGrid />
        </>
      ) : tab === "roles" ? (
        <PermsTable />
      ) : (
        <>
          <div className="row" style={{ marginBottom: 12, gap: 8, flexWrap: "wrap" }}>
            <div className="inwrap">
              <Ic n="search" s={13} />
              <input className="input search-sm" id="mem-q" placeholder="Search by name or email" value={u.memQ || ""} onChange={(e) => set("memQ", e.target.value)} aria-label="Search members" />
            </div>
            <div className="seg">
              {["all", ...ROLES].map((r) => (
                <button key={r} className={role === r ? "on" : ""} onClick={() => set("memRole", r)}>
                  {r === "all" ? "All" : r}
                </button>
              ))}
            </div>
          </div>
          <div className="panel" style={{ overflowX: "auto" }}>
            {ms.length ? (
              <table className="perm-t" style={{ minWidth: 880 }}>
                <thead>
                  <tr>
                    <th style={{ paddingLeft: 14 }}>Member</th>
                    <th style={{ textAlign: "left" }}>Role</th>
                    <th style={{ textAlign: "left" }}>Team</th>
                    <th>Active projects</th>
                    <th>Tasks</th>
                    <th style={{ textAlign: "left" }}>Last active</th>
                    <th style={{ textAlign: "left" }}>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {ms.map((m) => {
                    const ap = visibleProjects().filter((p) => p.members.includes(m.id) && p.status !== "complete").length;
                    const ot = allTasks().filter((t) => t.assignee === m.id && t.status !== "done").length;
                    return (
                      <tr key={m.id} onContextMenu={ctx(m.id)}>
                        <td style={{ paddingLeft: 14 }}>
                          <button className="row" onClick={() => go("member", { id: m.id })} style={{ gap: 10, textAlign: "left" }}>
                            <Av id={m.id} cls="md" tip={false} />
                            <span className="col">
                              <b style={{ fontWeight: 500 }}>
                                {m.name}
                                {m.id === D().me && (
                                  <span className="faint" style={{ fontWeight: 400 }}>
                                    {" "}
                                    (you)
                                  </span>
                                )}
                              </b>
                              <span className="faint" style={{ fontSize: 12 }}>
                                {m.email}
                              </span>
                            </span>
                          </button>
                        </td>
                        <td style={{ textAlign: "left" }}>
                          {isAdmin && m.role !== "Owner" && m.id !== D().me ? (
                            <button className="pillbtn bordered" onClick={(e) => openPop(e.currentTarget, "role", { id: m.id })}>
                              {m.role}
                              <Ic n="chevron-down" s={12} />
                            </button>
                          ) : (
                            <span className="pillbtn">
                              {m.role === "Owner" && <Ic n="crown" s={13} />}
                              {m.role}
                            </span>
                          )}
                        </td>
                        <td style={{ textAlign: "left" }}>
                          <span className="row">
                            <Ic n={TM(m.team).icon} s={13} />
                            {TM(m.team).name}
                          </span>
                        </td>
                        <td className="num">{ap}</td>
                        <td className="num">{ot}</td>
                        <td style={{ textAlign: "left" }} className="muted">
                          {m.last == null ? "—" : m.last < 5 ? <span style={{ color: "var(--green)" }}>Online</span> : ago(minsAgo(m.last))}
                        </td>
                        <td style={{ textAlign: "left" }}>
                          {m.status === "invited" ? (
                            <span className="badge amber">
                              <span className="dot" />
                              Invited
                            </span>
                          ) : m.status === "deactivated" ? (
                            <span className="badge gray">Deactivated</span>
                          ) : (
                            <span className="badge green">
                              <span className="dot" />
                              Active
                            </span>
                          )}
                        </td>
                        <td>
                          <button className="ibtn ibtn-sm" onClick={ctx(m.id)} aria-label="Member options">
                            <Ic n="ellipsis" s={14} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <Empty icon="search-x" title="No results found" text="No members match that search." cls="sm" />
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function Teams() {
  return (
    <div className="page">
      <div className="ph">
        <div>
          <h1>Teams</h1>
          <p>Groups of people who work on projects together.</p>
        </div>
        <div className="acts">
          {allowed("members:manage") && (<button className="btn btn-primary" onClick={newTeam}>
            <Ic n="plus" s={14} />
            New team
          </button>)}
        </div>
      </div>
      {teamsList().length ? (
        <TeamsGrid />
      ) : (
        <div className="panel">
          <Empty icon="users" title="No teams yet" text="Create a team to group people and give projects an owner.">
            {allowed("members:manage") && (<button className="btn btn-primary btn-sm" onClick={newTeam}>
              <Ic n="plus" s={14} />
              New team
            </button>)}
          </Empty>
        </div>
      )}
    </div>
  );
}

export function TeamPage() {
  const { params } = useRoute();
  const t = team(params.id);
  if (!t) return <NotFound />;
  const ms = D().members.filter((m) => m.team === t.id);
  const ps = visibleProjects().filter((p) => p.team === t.id);
  const ts = allTasks().filter((x) => ms.some((m) => m.id === x.assignee) && x.status !== "done");
  return (
    <div className="page">
      <div className="ph">
        <div className="row" style={{ gap: 12 }}>
          <span className="picon lg" style={{ "--c": t.c } as React.CSSProperties}>
            <Ic n={t.icon} s={18} />
          </span>
          <div>
            <h1>{t.name}</h1>
            <p style={{ margin: "2px 0 0" }}>{t.desc}</p>
          </div>
        </div>
        <div className="acts">
          {allowed("members:manage") && (<button className="btn btn-secondary" onClick={() => editTeam(t.id)}>
            <Ic n="pencil" s={14} />
            Edit team
          </button>)}
          {canInvite() && (<button className="btn btn-secondary" onClick={invite}>
            <Ic n="user-plus" s={14} />
            Invite to workspace
          </button>)}
        </div>
      </div>
      <div className="grid2">
        <div className="stack">
          <section className="panel">
            <div className="panel-h">
              <h2>Projects</h2>
              <span className="faint">{ps.length}</span>
            </div>
            {ps.length ? (
              ps.map((p) => (
                <div key={p.id} className="mini" onClick={() => go("project", { id: p.key })}>
                  <PIcon p={p} s={14} />
                  <span className="tt">{p.name}</span>
                  <PStatus s={p.status} />
                  <span className="row" style={{ width: 120 }}>
                    <ProgBar v={progressOf(p.id)} />
                  </span>
                </div>
              ))
            ) : (
              <div className="panel-b faint">No projects</div>
            )}
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Open tasks</h2>
              <span className="faint">{ts.length}</span>
            </div>
            {sortTasks(ts, { f: "due", dir: 1 })
              .slice(0, 8)
              .map((x) => (
                <MiniRow key={x.id} t={x} />
              ))}
          </section>
        </div>
        <section className="panel" style={{ alignSelf: "start" }}>
          <div className="panel-h">
            <h2>Members</h2>
            <span className="faint">{ms.length}</span>
          </div>
          {ms.map((m) => (
            <div key={m.id} className="mini" style={{ minHeight: 48 }} onClick={() => go("member", { id: m.id })}>
              <Av id={m.id} cls="md" tip={false} />
              <div className="grow">
                <div style={{ fontWeight: 500 }}>{m.name}</div>
                <div className="faint" style={{ fontSize: 12 }}>
                  {m.title}
                </div>
              </div>
              <span className="badge">{m.role}</span>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

export function MemberPage() {
  const { params } = useRoute();
  const m = mem(params.id);
  if (!m) return <NotFound />;
  const ts = allTasks().filter((t) => t.assignee === m.id);
  const open = ts.filter((t) => t.status !== "done");
  const done = ts.filter((t) => t.status === "done");
  const ps = visibleProjects().filter((p) => p.members.includes(m.id) && p.status !== "complete" && canSee(p));
  const acts = D()
    .activity.filter((a) => a.by === m.id)
    .slice(0, 8);
  const tab = S.ui.memTab || "assigned";
  const list = tab === "assigned" ? sortTasks(open, { f: "due", dir: 1 }) : done;
  return (
    <div className="page">
      <div className="row" style={{ gap: 18, marginBottom: 22, flexWrap: "wrap", alignItems: "flex-start" }}>
        <Av id={m.id} cls={`xl ${m.last != null && m.last < 5 ? "presence" : ""}`} tip={false} />
        <div className="grow" style={{ minWidth: 220 }}>
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            <h1 style={{ fontSize: "var(--fs-2xl)", margin: 0, fontWeight: 600, letterSpacing: "-.02em" }}>{m.name}</h1>
            <span className="badge">
              {m.role === "Owner" && <Ic n="crown" s={11} />}
              {m.role}
            </span>
            {m.status === "invited" && <span className="badge amber">Invite pending</span>}
          </div>
          <div className="muted" style={{ marginTop: 3 }}>
            {m.title} · {TM(m.team).name}
          </div>
          <div className="row faint" style={{ marginTop: 8, gap: 14, fontSize: 12.5, flexWrap: "wrap" }}>
            <span className="row" style={{ gap: 5 }}>
              <Ic n="mail" s={13} />
              <span style={{ userSelect: "all" }}>{m.email}</span>
            </span>
            <span className="row" style={{ gap: 5 }}>
              <Ic n="map-pin" s={13} />
              {m.tz}
            </span>
            <span className="row" style={{ gap: 5 }}>
              <Ic n="clock" s={13} />
              {m.last == null ? "Never signed in" : m.last < 5 ? "Online now" : "Active " + ago(minsAgo(m.last))}
            </span>
          </div>
        </div>
        <div className="row">
          <button className="btn btn-secondary" onClick={() => copyEmail(m.id)}>
            <Ic n="copy" s={14} />
            Copy email
          </button>
          <button className="btn btn-primary" onClick={() => newTask({ assignee: m.id })}>
            <Ic n="plus" s={14} />
            Assign task
          </button>
          <button className="ibtn" onClick={ctx(m.id)} aria-label="More">
            <Ic n="ellipsis" s={16} />
          </button>
        </div>
      </div>
      <div className="stats" style={{ marginBottom: 18 }}>
        <div className="stat">
          <span className="k">Active projects</span>
          <span className="v">{ps.length}</span>
        </div>
        <div className="stat">
          <span className="k">Assigned tasks</span>
          <span className="v">{open.length}</span>
        </div>
        <div className="stat">
          <span className="k">Completed tasks</span>
          <span className="v">{done.length}</span>
        </div>
        <div className="stat">
          <span className="k">Overdue</span>
          <span className="v" style={open.filter(isOver).length ? { color: "var(--red)" } : undefined}>
            {open.filter(isOver).length}
          </span>
        </div>
      </div>
      <div className="grid2">
        <section className="panel">
          <div className="tabs" style={{ padding: "0 8px" }}>
            {[
              ["assigned", `Assigned · ${open.length}`],
              ["completed", `Completed · ${done.length}`],
            ].map(([k, n]) => (
              <button key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => set("memTab", k!)}>
                {n}
              </button>
            ))}
          </div>
          {list.length ? list.map((t) => <MiniRow key={t.id} t={t} av={false} />) : <Empty icon="list-checks" title="No tasks here" text="Nothing to show in this list." cls="sm" />}
        </section>
        <div className="stack">
          <section className="panel">
            <div className="panel-h">
              <h2>Active projects</h2>
            </div>
            {ps.length ? (
              ps.map((p) => (
                <div key={p.id} className="mini" onClick={() => go("project", { id: p.key })}>
                  <PIcon p={p} s={14} />
                  <span className="tt">{p.name}</span>
                  <span className="faint" style={{ fontSize: 12 }}>
                    {p.lead === m.id ? "Lead" : "Member"}
                  </span>
                </div>
              ))
            ) : (
              <div className="panel-b faint">No active projects</div>
            )}
          </section>
          <section className="panel">
            <div className="panel-h">
              <h2>Recent activity</h2>
            </div>
            <div className="panel-b feed">{acts.length ? acts.map((a) => <ActItem key={a.id} a={a} />) : <span className="faint">No recent activity</span>}</div>
          </section>
        </div>
      </div>
    </div>
  );
}
