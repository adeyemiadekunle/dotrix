// Gr8r's shell (gr8r-studio/src/shell/layout.js): sidebar, top bar, the page, and on phones a
// bottom bar. dotrix adds Chat to the Workspace group; the Inbox holds people's items and
// Notifications the agents' (approvals, plans, findings).
import { useEffect, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";

import { openPop, projMove, toggleSide } from "../core/actions";
import { PSTAT } from "../core/constants";
import { Ic, WsLogo } from "../core/icons";
import { presence } from "../core/presence";
import { allowed } from "../core/can";
import { newProject, newTeam } from "../core/more";
import { go, useRoute, type Route } from "../core/nav";
import { MOD, TODAY, diffD, parse } from "../core/utils";
import { D, S, allTasks, pColor, projByKey, render, team, teamsList, useStudio, visibleProjects } from "../data/store";
import type { NotifType } from "../data/types";
import { Av } from "../ui/helpers";
import { PopLayer } from "../overlays/PopLayer";
import { Toasts } from "../ui/toast";
import { AgentsPanel, agentsShown, inCodeTab, panelWide, toggleAgents } from "./AgentsPanel";
import { Notices } from "./Notices";

export const PEOPLE_ITEMS: NotifType[] = ["mention", "assign", "comment"];
export const AGENT_ITEMS: NotifType[] = ["approval", "checkpoint", "finding", "decided", "update"];

export const ROUTE_NAMES: Record<string, string> = {
  home: "Home",
  inbox: "Inbox",
  mytasks: "My Tasks",
  favorites: "Favorites",
  notifications: "Notifications",
  search: "Search",
  overview: "Overview",
  projects: "Projects",
  tasks: "Tasks",
  calendar: "Calendar",
  timeline: "Timeline",
  members: "Members",
  member: "Member",
  teams: "Teams",
  team: "Team",
  activity: "Activity",
  settings: "Settings",
  archive: "Archive",
  chat: "Chat",
  system: "Design system",
  states: "System states",
};

/** A page's name; Chat is "Code" while its Code tab is open. */
export const routeName = (route: string) => (route === "chat" && new URLSearchParams(location.search).get("tab") === "coding" ? "Code" : ROUTE_NAMES[route]);

const css = (o: Record<string, string | number>) => o as CSSProperties;

// Below 900px the sidebar is a drawer (280px wide): always with its labels, whatever the
// collapsed setting says (that's for the wide layout).
const NARROW = "(max-width: 900px)";
const narrow = () => typeof window !== "undefined" && window.matchMedia(NARROW).matches;
/** The sidebar shows icons only: collapsed, on a wide screen. */
export const sideCollapsed = () => S.ui.collapsed && !narrow();

/** A collapsed sidebar's labels on hover or focus. They float over the page: the sidebar clips
 * anything that overflows it, so CSS tooltips (`data-tip`) can't show from inside it. */
function SideTip() {
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);
  useEffect(() => {
    const side = document.querySelector<HTMLElement>("nav.side");
    if (!side) return;
    const show = (e: Event) => {
      const el = (e.target as HTMLElement).closest<HTMLElement>("[data-tip]");
      if (!el || !side.contains(el) || !sideCollapsed()) return setTip(null);
      const r = el.getBoundingClientRect();
      setTip({ text: el.dataset.tip!, x: r.right + 8, y: r.top + r.height / 2 });
    };
    const hide = () => setTip(null);
    side.addEventListener("pointerover", show);
    side.addEventListener("focusin", show);
    side.addEventListener("pointerleave", hide);
    side.addEventListener("focusout", hide);
    side.addEventListener("click", hide);
    return () => {
      side.removeEventListener("pointerover", show);
      side.removeEventListener("focusin", show);
      side.removeEventListener("pointerleave", hide);
      side.removeEventListener("focusout", hide);
      side.removeEventListener("click", hide);
    };
  }, []);
  return tip ? (
    <div className="side-tip" role="tooltip" style={{ left: tip.x, top: tip.y }}>
      {tip.text}
    </div>
  ) : null;
}

export function Shell({ children }: { children: ReactNode }) {
  const s = useStudio();
  const u = s.ui;
  // Going to another page from anywhere in the drawer (a project, a view) closes it too.
  const { route: here, params: hereParams } = useRoute();
  const at = `${here}/${JSON.stringify(hereParams)}`;
  useEffect(() => {
    if (S.ui.mnav) {
      S.ui.mnav = false;
      render();
    }
  }, [at]);
  // Crossing the narrow breakpoint changes what "collapsed" means: re-render.
  useEffect(() => {
    const mqs = [window.matchMedia(NARROW), window.matchMedia("(min-width: 1200px)")];
    const onChange = () => render();
    mqs.forEach((mq) => mq.addEventListener("change", onChange));
    return () => mqs.forEach((mq) => mq.removeEventListener("change", onChange));
  }, []);
  return (
    <>
      <a className="skip" href="#main-content">
        Skip to content
      </a>
      <div className={`shell ${sideCollapsed() ? "collapsed" : ""} ${u.mnav ? "mnav" : ""} ${agentsShown() ? "with-agents" : ""}`}>
        <Sidebar />
        <SideTip />
        {u.mnav && <div className="side-scrim" onClick={() => ((S.ui.mnav = false), render())} />}
        <main className="main" id="main">
          <Topbar />
          {u.offline && (
            <div className="offline-bar" role="alert">
              <Ic n="wifi-off" s={15} />
              <span>
                <b>You&apos;re offline.</b> Changes won&apos;t be saved until your connection is back.
              </span>
              <span className="sp" />
              <button className="btn btn-sm btn-secondary" onClick={() => ((S.ui.offline = false), rerender())}>
                Try again
              </button>
            </div>
          )}
          <div className="content" id="main-content" tabIndex={-1}>
            {children}
          </div>
        </main>
        {agentsShown() && (
          <>
            {!panelWide() && <div className="agents-scrim" onClick={() => ((S.ui.agentsSheet = false), rerender())} />}
            <AgentsPanel />
          </>
        )}
        <BottomNav />
      </div>
      <PopLayer />
      {/* The panel lists the same things: notices only while it's closed. */}
      {!agentsShown() && <Notices />}
      <Toasts />
    </>
  );
}

/** A UI-only change: re-render, nothing to save. */
const rerender = () => render();

function SItem({
  route,
  label,
  icon,
  params,
  ct,
  dot,
  kbd,
  on,
  onClick,
}: {
  route?: Route;
  label: string;
  icon: string;
  params?: Record<string, string>;
  ct?: number | string;
  dot?: boolean;
  kbd?: string;
  on?: boolean;
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
}) {
  const { route: cur, params: curParams } = useRoute();
  const active = on ?? (route === cur && (!params?.id || params.id === curParams.id));
  return (
    <button
      className={`sitem ${active ? "on" : ""}`}
      onClick={(e) => {
        if (onClick) return onClick(e);
        if (!route) return;
        go(route, params);
        // On a narrow window the sidebar is a drawer: picking a page closes it, the page you're on too.
        if (narrow() && S.ui.mnav) {
          S.ui.mnav = false;
          render();
        }
      }}
      data-tip={sideCollapsed() ? label : undefined}
      data-tip-pos="right"
      aria-current={active ? "page" : undefined}
    >
      <Ic n={icon} s={16} />
      <span className="trunc">{label}</span>
      {ct ? <span className={`ct ${dot ? "dotc" : ""}`}>{ct}</span> : null}
      {kbd && (
        <span className="ct hide-m">
          <kbd>{kbd}</kbd>
        </span>
      )}
    </button>
  );
}

function Sidebar() {
  const { route, params } = useRoute();
  const u = S.ui;
  const d = D();
  const unreadInbox = d.notifs.filter((n) => !n.read && PEOPLE_ITEMS.includes(n.type)).length;
  const unreadAgents = d.notifs.filter((n) => !n.read && AGENT_ITEMS.includes(n.type)).length;
  const myOpen = allTasks().filter((t) => t.assignee === d.me && t.status !== "done" && t.due && diffD(parse(t.due)!, TODAY) <= 0).length;
  const projs = visibleProjects().filter((p) => p.status !== "complete");
  const inProj = route === "project" ? projByKey(params.id)?.id : null;
  const archived = d.tasks.filter((t) => t.archived).length + d.projects.filter((p) => p.archived).length;
  return (
    <nav className="side" aria-label="Main">
      <div className="side-top">
        <div className="row" style={{ gap: 2 }}>
          <button className="ws grow" onClick={(e) => openPop(e.currentTarget, "ws")} aria-haspopup="menu" aria-label="Switch workspace">
            <WsLogo w={d.ws} px={22} />
            <span className="ws-name trunc">{d.ws.name}</span>
            <span className="chev-d faint">
              <Ic n="chevrons-up-down" s={13} />
            </span>
          </button>
          {!sideCollapsed() && (
            // In the drawer (narrow screens) it closes the drawer; collapsing to icons is for wide screens.
            <button
              className="ibtn ibtn-sm hide-m"
              onClick={() => (narrow() ? ((S.ui.mnav = false), render()) : toggleSide())}
              data-tip={narrow() ? "Close menu" : "Collapse sidebar  ["}
              aria-label={narrow() ? "Close menu" : "Collapse sidebar"}
            >
              <Ic n="panel-left" s={15} />
            </button>
          )}
        </div>
      </div>
      <div className="side-scroll">
        {sideCollapsed() && (
          <button className="sitem" onClick={toggleSide} data-tip="Expand sidebar" data-tip-pos="right" aria-label="Expand sidebar">
            <Ic n="panel-left" s={16} />
          </button>
        )}
        <SItem route="home" label="Home" icon="house" />
        <SItem route="inbox" label="Inbox" icon="inbox" ct={unreadInbox || ""} dot />
        <SItem route="mytasks" label="My Tasks" icon="circle-check" ct={myOpen || ""} />
        <SItem route="favorites" label="Favorites" icon="star" />
        <SItem route="notifications" label="Notifications" icon="bell" ct={unreadAgents || ""} />
        <div className="sgroup">
          <div className="sgroup-h">Workspace</div>
          <SItem route="overview" label="Overview" icon="layout-dashboard" />
          <SItem route="chat" label="Chat" icon="message-square" />
          <SItem route="projects" label="Projects" icon="folder-kanban" />
          <SItem route="tasks" label="Tasks" icon="list-checks" />
          <SItem route="calendar" label="Calendar" icon="calendar" />
          <SItem route="timeline" label="Timeline" icon="chart-gantt" />
          <SItem route="members" label="Members" icon="users" />
          <SItem route="activity" label="Activity" icon="activity" />
        </div>
        <div className="sgroup" id="side-projects">
          <div className="sgroup-h">
            <span>Projects</span>
            <span className="sp" />
            {allowed("projects:manage") && (
              <button className="ibtn ibtn-xs" onClick={newProject} data-tip="New project  P" aria-label="New project">
                <Ic n="plus" s={14} />
              </button>
            )}
          </div>
          {projs.map((p) => {
            const open = Boolean(u.expanded[p.id]);
            const on = inProj === p.id;
            return (
              <div className="sproj" key={p.id}>
                <div
                  className={`sitem ${on ? "on" : ""}`}
                  role="link"
                  tabIndex={0}
                  onClick={() => go("project", { id: p.key })}
                  onKeyDown={(e) => e.key === "Enter" && go("project", { id: p.key })}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id });
                  }}
                  data-tip={sideCollapsed() ? p.name : undefined}
                  data-tip-pos="right"
                >
                  <span
                    className="pico"
                    style={css({ "--c": pColor(p) })}
                    onClick={(e) => {
                      e.stopPropagation();
                      u.expanded[p.id] = !open;
                      rerender();
                    }}
                    aria-label="Toggle sub-pages"
                  >
                    <Ic n={p.icon} s={12} />
                  </span>
                  <span className="trunc">{p.name}</span>
                  {p.fav && (
                    <span className="fav">
                      <Ic n="star" s={11} />
                    </span>
                  )}
                  {p.private && (
                    <span className="faint" style={{ marginLeft: 4 }}>
                      <Ic n="lock" s={11} />
                    </span>
                  )}
                  <span className="sdot" style={{ background: PSTAT[p.status].c }} title={PSTAT[p.status].name} />
                  <span className="hov">
                    <span
                      className="ibtn ibtn-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id });
                      }}
                      aria-label="Project options"
                    >
                      <Ic n="ellipsis" s={14} />
                    </span>
                    <span
                      className="ibtn ibtn-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        u.expanded[p.id] = !open;
                        rerender();
                      }}
                      aria-label="Expand"
                    >
                      <Ic n="chevron-right" s={13} cls={`chev ${open ? "open" : ""}`} />
                    </span>
                  </span>
                </div>
                <div className={`sub ${open && !sideCollapsed() ? "open" : ""}`}>
                  {(
                    [
                      ["board", "Board", "square-kanban"],
                      ["list", "List", "list"],
                      ["timeline", "Timeline", "chart-gantt"],
                      ["files", "Files", "paperclip"],
                      ["knowledge", "Knowledge", "book-open"],
                    ] as const
                  ).map(([tab, n, i]) => (
                    <button key={tab} className={`sitem ${on && params.tab === tab ? "on" : ""}`} onClick={() => go("project", { id: p.key, tab })}>
                      <Ic n={i} s={14} />
                      <span>{n}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
          <SItem route="archive" label="Archive" icon="archive" ct={archived || ""} />
        </div>
        <div className="sgroup">
          <div className="sgroup-h">
            <span>Teams</span>
            <span className="sp" />
            {allowed("members:manage") && (
              <button className="ibtn ibtn-xs" onClick={newTeam} data-tip="New team" aria-label="New team">
                <Ic n="plus" s={14} />
              </button>
            )}
          </div>
          {teamsList().map((t) => (
            <SItem key={t.id} route="team" label={t.name} icon={t.icon} params={{ id: t.id }} />
          ))}
        </div>
      </div>
      <div className="side-bot">
        <button className="sitem" onClick={(e) => openPop(e.currentTarget, "help")} data-tip={sideCollapsed() ? "Help" : undefined} data-tip-pos="right">
          <Ic n="circle-help" s={16} />
          <span>Help &amp; resources</span>
        </button>
        <SItem route="settings" label="Settings" icon="settings" />
        <button
          className="sitem"
          onClick={(e) => openPop(e.currentTarget, "user")}
          style={{ height: 36 }}
          data-tip={sideCollapsed() ? "Profile" : undefined}
          data-tip-pos="right"
        >
          <Av id={d.me} cls="presence" tip={false} />
          <span className="trunc" style={{ color: "var(--text)", fontWeight: 500 }}>
            {S.prefs.name}
          </span>
          <span className="ct">
            <Ic n="chevrons-up-down" s={13} />
          </span>
        </button>
      </div>
    </nav>
  );
}

function Crumbs() {
  const { route, params } = useRoute();
  const out: ReactNode[] = [];
  const c = (label: string, onClick?: () => void, cur = false, icon?: ReactNode) => (
    <button key={label} className={cur ? "cur" : ""} onClick={onClick}>
      {icon}
      {label}
    </button>
  );
  if (route === "project") {
    const p = projByKey(params.id);
    out.push(c("Projects", () => go("projects")));
    if (p)
      out.push(
        c(
          p.name,
          () => go("project", { id: p.key, tab: "overview" }),
          true,
          <span
            className="pico"
            style={css({
              "--c": pColor(p),
              width: 16,
              height: 16,
              borderRadius: 4,
              display: "grid",
              placeItems: "center",
              color: pColor(p),
            })}
          >
            <Ic n={p.icon} s={11} />
          </span>,
        ),
      );
  } else if (route === "member") {
    out.push(c("Members", () => go("members")));
    out.push(c(D().members.find((m) => m.id === params.id)?.name || "Member", undefined, true));
  } else if (route === "team") {
    out.push(c("Teams", () => go("teams")));
    out.push(c(team(params.id)?.name || "Team", undefined, true));
  } else out.push(c(routeName(route) || "Not found", undefined, true));
  return (
    <nav className="crumbs trunc" aria-label="Breadcrumb">
      {out.flatMap((x, i) =>
        i
          ? [
              <span key={`s${i}`} className="sep">
                /
              </span>,
              x,
            ]
          : [x],
      )}
    </nav>
  );
}

function Topbar() {
  const unread = D().notifs.some((n) => !n.read);
  const waiting = presence().filter((p) => p.state === "needs" || p.state === "blocked").length;
  return (
    <header className="topbar">
      <button className="ibtn mnav-btn" onClick={() => ((S.ui.mnav = true), rerender())} aria-label="Open navigation">
        <Ic n="menu" s={17} />
      </button>
      <Crumbs />
      <span className="sp" />
      <button className="topsearch" onClick={() => openPaletteSoon()} aria-label="Search and commands">
        <Ic n="search" s={14} />
        <span className="lbltxt">Search or jump to…</span>
        <span className="kbd">{MOD}K</span>
      </button>
      {!inCodeTab() && (
        <button
          className={`ibtn ${agentsShown() ? "on" : ""}`}
          onClick={toggleAgents}
          data-tip="Agents"
          aria-label={agentsShown() ? "Hide the agents panel" : "Show the agents panel"}
          aria-pressed={agentsShown()}
          style={{ position: "relative" }}
        >
          <Ic n="bot" s={16} />
          {waiting > 0 && !agentsShown() && <span className="top-dot" />}
        </button>
      )}
      <button className="ibtn" onClick={() => go("notifications")} data-tip="Notifications" aria-label="Notifications" style={{ position: "relative" }}>
        <Ic n="bell" s={16} />
        {unread && (
          <span
            style={{
              position: "absolute",
              top: 6,
              right: 7,
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "var(--acc)",
              boxShadow: "0 0 0 2px var(--surface)",
            }}
          />
        )}
      </button>
      <button className="btn btn-secondary btn-sm" onClick={(e) => openPop(e.currentTarget, "create")} aria-haspopup="menu" aria-label="Create new">
        <Ic n="plus" s={14} />
        <span className="hide-m">New</span>
        <Ic n="chevron-down" s={12} cls="hide-m" />
      </button>
      <button className="ibtn hide-m" onClick={(e) => openPop(e.currentTarget, "user")} aria-label="Account menu" style={{ width: "auto", padding: "0 2px" }}>
        <Av id={D().me} cls="md" tip={false} />
      </button>
    </header>
  );
}

/** The command palette opens through overlays/Palette; set at startup. */
export let openPaletteSoon: () => void = () => {};
export function setPaletteOpener(f: () => void) {
  openPaletteSoon = f;
}

function BottomNav() {
  const { route } = useRoute();
  const unread = D().notifs.some((n) => !n.read && PEOPLE_ITEMS.includes(n.type));
  const b = (r: Route, label: string, icon: string, extra?: ReactNode) => (
    <button className={route === r ? "on" : ""} onClick={() => go(r)}>
      <Ic n={icon} s={19} />
      <span>{label}</span>
      {extra}
    </button>
  );
  return (
    <nav className="bottomnav" aria-label="Primary">
      {b("home", "Home", "house")}
      {b("mytasks", "My Tasks", "circle-check")}
      {b("projects", "Projects", "folder-kanban")}
      {b("inbox", "Inbox", "inbox", unread ? <span className="bdot" /> : null)}
      <button onClick={() => ((S.ui.mnav = true), rerender())}>
        <Ic n="ellipsis" s={19} />
        <span>More</span>
      </button>
    </nav>
  );
}

export { projMove };
