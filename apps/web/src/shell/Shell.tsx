import { ActionButton } from "@dotrix/ui/components/action-button";
// Shell: sidebar, top bar, the page, and on phones a
// bottom bar. dotrix adds Chat to the Workspace group; the Inbox holds people's items and the
// agents' (approvals, plans, findings).
import { useEffect, type MouseEvent, type ReactNode } from "react";

import { openPop, toggleSide } from "../core/actions";
import { PSTAT } from "../core/constants";
import { Ic, WsLogo } from "../core/icons";
import { allowed } from "../core/can";
import { newProject } from "../core/more";
import { go, href, useRoute, type Route } from "../core/nav";
import { MOD, TODAY, diffD, parse } from "../core/utils";
import { D, S, projByKey, render, useStudio } from "../data/store";
import { useMembers, useNotifs, useProjects } from "../data/lists";
import { useAllTasks } from "../data/tasks";
import { isMine, tasksLabel } from "../core/features";
import { Av } from "../ui/helpers";
import { PopLayer } from "../overlays/PopLayer";
import { AppShell, SideNav, SideNavItem, SideNavSection, TopNav, Breadcrumbs, BreadcrumbItem, Button, IconButton, Banner } from "@dotrix/ui/astryx";
import { AgentsLauncher, AgentsPanel, agentsShown, inCodeTab } from "./AgentsPanel";
import { desktopApp } from "../core/desktop";
import { UpdateBar, openWhatsNew, useWhatsNewAfterUpdate } from "./DesktopApp";
import { Notices } from "./Notices";

export const ROUTE_NAMES: Record<string, string> = {
  home: "Home",
  inbox: "Inbox",
  mytasks: "My Tasks",
  tasks: "Tasks",
  favorites: "Favorites",
  notifications: "Notifications",
  search: "Search",
  overview: "Overview",
  projects: "Projects",
  members: "Members",
  member: "Member",
  teams: "Teams",
  team: "Team",
  activity: "Activity",
  settings: "Settings",
  archive: "Archive",
  chat: "Chat",
  codes: "Codes",
};

/** A page's name. */
export const routeName = (route: string) => (route === "mytasks" ? tasksLabel() : ROUTE_NAMES[route]);

const NARROW = "(max-width: 900px)";
const narrow = () => typeof window !== "undefined" && window.matchMedia(NARROW).matches;
const sideCollapsed = () => S.ui.collapsed && !narrow();

function WorkspaceSwitcher() {
  const workspace = D().ws;
  return (
    <Button
      label="Switch workspace"
      aria-label="Switch workspace"
      aria-haspopup="menu"
      aria-expanded={S.ui.pop?.type === "ws"}
      aria-controls={S.ui.pop?.type === "ws" ? "workspace-menu" : undefined}
      className="workspace-switcher"
      width="100%"
      variant="ghost"
      onClick={(event) => openPop(event.currentTarget, "ws")}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown" && S.ui.pop?.type !== "ws") {
          event.preventDefault();
          openPop(event.currentTarget, "ws");
        }
      }}
    >
      <span className="workspace-switcher-content">
        <WsLogo w={workspace} px={22} />
        <span className="workspace-switcher-name">{workspace.name}</span>
        <Ic n="chevrons-up-down" s={13} cls="workspace-switcher-caret" />
      </span>
    </Button>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { ui } = useStudio();
  const { route, params } = useRoute();
  const at = `${route}/${JSON.stringify(params)}`;
  useWhatsNewAfterUpdate();
  useEffect(() => {
    if (S.ui.mnav) {
      S.ui.mnav = false;
      render();
    }
  }, [at]);
  useEffect(() => {
    const query = window.matchMedia(NARROW);
    const update = () => render();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const openNavigation = () => {
    S.ui.mnav = true;
    render();
  };
  return (
    <>
      <AppShell
        className="workspace-shell"
        height="fill"
        variant="elevated"
        contentPadding={0}
        sideNav={<Sidebar />}
        topNav={<Topbar />}
        mobileNav={{
          breakpoint: "md",
          isOpen: ui.mnav,
          onOpenChange: (open) => {
            S.ui.mnav = open;
            render();
          },
        }}
        banner={
          <>
            <UpdateBar />
            {ui.offline && (
              <Banner
                status="warning"
                title="You're offline"
                description="Changes won't be saved until your connection is back."
                endContent={
                  <Button
                    label="Try again"
                    onClick={() => {
                      S.ui.offline = false;
                      render();
                    }}
                  />
                }
              />
            )}
          </>
        }
      >
        {!agentsShown() && <Notices />}
        <div className="content" id="main-content" tabIndex={-1}>
          {children}
        </div>
        {agentsShown() && (
          <>
            <div
              className="agents-scrim"
              onClick={() => {
                S.ui.agentsSheet = false;
                render();
              }}
            />
            <AgentsPanel />
          </>
        )}
        <BottomNav openNavigation={openNavigation} />
      </AppShell>
      <PopLayer />
    </>
  );
}

function Sidebar() {
  const { route, params } = useRoute();
  const d = D();
  const unread = useNotifs().items.filter((n) => !n.read).length;
  const due = useAllTasks().tasks.filter((t) => isMine(t) && t.status !== "done" && t.due && diffD(parse(t.due)!, TODAY) <= 0).length;
  const projects = useProjects().items.filter((p) => p.status !== "complete");
  const current = route === "project" ? projByKey(params.id)?.id : null;
  const visit = (r: Route, p?: Record<string, string>) => {
    go(r, p);
    S.ui.mnav = false;
    render();
  };
  return (
    <SideNav
      id="main-navigation"
      aria-label="Main"
      className="workspace-navigation"
      collapsible={{ isCollapsed: sideCollapsed(), onCollapsedChange: () => toggleSide(), hasButton: true }}
      header={<WorkspaceSwitcher />}
      footer={
        <>
          {desktopApp() && <SideNavItem size={S.prefs.side === "compact" ? "sm" : "md"} label="What's new" icon={<Ic n="gift" />} onClick={openWhatsNew} />}
          <SideNavItem
            size={S.prefs.side === "compact" ? "sm" : "md"}
            label="Help & resources"
            icon={<Ic n="circle-help" />}
            onClick={(e) => openPop(e.currentTarget, "help")}
          />
          <SideNavItem
            size={S.prefs.side === "compact" ? "sm" : "md"}
            label="Settings"
            icon={<Ic n="settings" />}
            isSelected={route === "settings"}
            href={href("settings")}
          />
          <SideNavItem
            size={S.prefs.side === "compact" ? "sm" : "md"}
            label={S.prefs.name}
            icon={<Av id={d.me} tip={false} />}
            onClick={(e) => openPop(e.currentTarget, "user")}
          />
        </>
      }
    >
      <SideNavSection title="Workspace" isHeaderHidden>
        {(
          [
            ["home", "Home", "house"],
            ["inbox", "Inbox", "inbox"],
            ["mytasks", tasksLabel(), "circle-check"],
            ["chat", "Chat", "message-square"],
            ["codes", "Codes", "code"],
            ["projects", "Projects", "folder-kanban"],
            ["activity", "Activity", "activity"],
          ] as [Route, string, string][]
        ).map(([r, label, icon]) => (
          <SideNavItem
            size={S.prefs.side === "compact" ? "sm" : "md"}
            key={r}
            label={label}
            icon={<Ic n={icon} s={18} />}
            href={href(r)}
            isSelected={route === r}
            endContent={r === "inbox" && unread ? <span>{unread}</span> : r === "mytasks" && due ? <span>{due}</span> : undefined}
          />
        ))}
      </SideNavSection>
      <SideNavSection
        title="Projects"
        endContent={allowed("projects:manage") ? <IconButton label="New project" icon={<Ic n="plus" />} size="sm" onClick={newProject} /> : undefined}
      >
        {projects.map((p) => (
          <SideNavItem
            size={S.prefs.side === "compact" ? "sm" : "md"}
            key={p.id}
            label={p.name}
            href={href("project", { id: p.key })}
            icon={<Ic n={p.icon} s={16} />}
            isSelected={current === p.id}
            collapsible={{
              isCollapsed: !S.ui.expanded[p.id],
              onCollapsedChange: (collapsed) => {
                S.ui.expanded[p.id] = !collapsed;
                render();
              },
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id });
            }}
            endContent={<span className="sdot" style={{ background: PSTAT[p.status].c }} title={PSTAT[p.status].name} />}
            actions={
              <IconButton
                label={`Options for ${p.name}`}
                icon={<Ic n="ellipsis" />}
                size="sm"
                onClick={(e) => openPop(e.currentTarget, "ctx", { ctx: "project", id: p.id })}
              />
            }
          >
            {(
              [
                ["board", "Board", "square-kanban"],
                ["list", "List", "list"],
                ["knowledge", "Knowledge", "book-open"],
              ] as const
            ).map(([tab, label, icon]) => (
              <SideNavItem
                size={S.prefs.side === "compact" ? "sm" : "md"}
                key={tab}
                label={label}
                icon={<Ic n={icon} s={15} />}
                isSelected={current === p.id && params.tab === tab}
                onClick={() => visit("project", { id: p.key, tab })}
              />
            ))}
          </SideNavItem>
        ))}
      </SideNavSection>
    </SideNav>
  );
}

function Crumbs() {
  const { items: members } = useMembers();
  const { route, params } = useRoute();
  const project = route === "project" ? projByKey(params.id) : undefined;
  return (
    <Breadcrumbs label="Breadcrumb">
      {project && <BreadcrumbItem href={href("projects")}>Projects</BreadcrumbItem>}
      {route === "member" && <BreadcrumbItem href={href("members")}>Members</BreadcrumbItem>}
      <BreadcrumbItem isCurrent>
        {project?.name ?? (route === "member" ? members.find((m) => m.id === params.id)?.name : routeName(route)) ?? "Not found"}
      </BreadcrumbItem>
    </Breadcrumbs>
  );
}

function Topbar() {
  const unread = useNotifs().items.some((n) => !n.read);
  return (
    <TopNav
      label="Workspace actions"
      className="workspace-topbar"
      heading={narrow() ? <WorkspaceSwitcher /> : undefined}
      startContent={
        <>
          <Crumbs />
        </>
      }
      endContent={
        <>
          <button className="topsearch" onClick={() => openPaletteSoon()} aria-label="Search and commands">
            <Ic n="search" s={14} />
            <span className="lbltxt">Search or jump to…</span>
            <span className="kbd">{MOD}K</span>
          </button>
          <ActionButton className="ibtn" onClick={() => go("inbox")} data-tip="Inbox" aria-label="Inbox" style={{ position: "relative" }}>
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
          </ActionButton>
          {!inCodeTab() && <AgentsLauncher inline />}
          <ActionButton className="btn btn-secondary btn-sm" onClick={(e) => openPop(e.currentTarget, "create")} aria-haspopup="menu" aria-label="Create new">
            <Ic n="plus" s={14} />
            <span className="hide-m">New</span>
            <Ic n="chevron-down" s={12} cls="hide-m" />
          </ActionButton>
          <ActionButton
            className="ibtn hide-m"
            onClick={(e) => openPop(e.currentTarget, "user")}
            aria-label="Account menu"
            style={{ width: "auto", padding: "0 2px" }}
          >
            <Av id={D().me} cls="md" tip={false} />
          </ActionButton>
        </>
      }
    />
  );
}

/** The command palette opens through overlays/Palette; set at startup. */
export let openPaletteSoon: () => void = () => {};
export function setPaletteOpener(f: () => void) {
  openPaletteSoon = f;
}

function BottomNav({ openNavigation }: { openNavigation: (e: MouseEvent<HTMLButtonElement>) => void }) {
  const { route } = useRoute();
  const unread = useNotifs().items.some((n) => !n.read);
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
      {b("mytasks", tasksLabel(), "circle-check")}
      {b("projects", "Projects", "folder-kanban")}
      {b("inbox", "Inbox", "inbox", unread ? <span className="bdot" /> : null)}
      <button onClick={openNavigation} aria-controls="main-navigation" aria-expanded={S.ui.mnav}>
        <Ic n="ellipsis" s={19} />
        <span>More</span>
      </button>
    </nav>
  );
}
