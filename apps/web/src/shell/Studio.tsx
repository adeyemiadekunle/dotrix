// The workspace app (Gr8r's render loop, gr8r-studio/src/shell/render.js): your preferences on
// <html>, the page title, the shell with the screen for the URL, and the overlay layers.
import { useEffect, useState, type ReactNode } from "react";

import { hasSession } from "@/lib/api";

import { applyPrefs } from "../core/theme";
import { Ic } from "../core/icons";
import { WS, back, currentSlug, go, useRoute, type Route } from "../core/nav";
import { live, loadWorkspace, onLoaded, showDemo } from "../data/live";
import { loadInvites } from "../data/account";
import { DesignSystem, SystemStates } from "../screens/DesignSystem";
import { D, projByKey, team, useStudio } from "../data/store";
import { Drawer } from "../overlays/Drawer";
import { ModalLayer } from "../overlays/Modals";
import { installDragDrop } from "../core/dragdrop";
import { installKeyboard } from "../core/keyboard";
import { Palette } from "../overlays/Palette";
import { Archive } from "../screens/Archive";
import { Chat } from "../screens/Chat";
import { MemberPage, Members, TeamPage, Teams } from "../screens/Members";
import { Settings } from "../screens/Settings";
import { Home } from "../screens/Home";
import { Inbox, Notifications } from "../screens/Inbox";
import { Project } from "../screens/Project";
import { Overview, Projects } from "../screens/Projects";
import { Search } from "../screens/Search";
import { ActivityPage, CalendarPage, Favorites, MyTasks, Tasks, TimelinePage } from "../screens/TaskPages";
import { Empty } from "../ui/helpers";
import { ROUTE_NAMES, Shell } from "./Shell";

// A real workspace's pending invites join its members once it loads (Members, Settings).
onLoaded.push(() => void loadInvites());

const SCREENS: Partial<Record<Route, () => ReactNode>> = {
  home: Home,
  mytasks: MyTasks,
  tasks: Tasks,
  calendar: CalendarPage,
  timeline: TimelinePage,
  favorites: Favorites,
  activity: ActivityPage,
  projects: Projects,
  project: Project,
  overview: Overview,
  search: Search,
  inbox: Inbox,
  notifications: Notifications,
  chat: Chat,
  members: Members,
  member: MemberPage,
  teams: Teams,
  team: TeamPage,
  archive: Archive,
  settings: Settings,
  system: DesignSystem,
  states: SystemStates,
};

/** Gr8r's 404 (gr8r-studio/src/pages/errors.js page404). */
function NotFound() {
  return (
    <div className="fullstate">
      <div className="box">
        <div className="empty-state" style={{ padding: 0 }}>
          <div className="glyph">
            <Ic n="file-question" s={20} />
          </div>
        </div>
        <span className="code">ERROR 404</span>
        <h1>Page not found</h1>
        <p>The page you&apos;re looking for was moved, deleted, or never existed. Check the link or head back home.</p>
        <div className="row">
          <button className="btn btn-secondary" onClick={back}>
            <Ic n="arrow-left" s={14} />
            Go back
          </button>
          <button className="btn btn-primary" onClick={() => go("home")}>
            Go to Home
          </button>
        </div>
      </div>
    </div>
  );
}

function Screen() {
  const { route } = useRoute();
  if (route === "notfound") return <NotFound />;
  const C = SCREENS[route];
  if (C) return <C />;
  return (
    <div className="page">
      <Empty icon="hammer" title={ROUTE_NAMES[route] ?? "Coming next"} text="This page isn't built yet." />
    </div>
  );
}

/** A whole-window message in the auth shell's place while a workspace can't be shown. */
function Full({ icon, title, text, children }: { icon: string; title: string; text: string; children?: ReactNode }) {
  return (
    <div className="fullstate" style={{ minHeight: "100svh" }}>
      <div className="box">
        <div className="empty-state" style={{ padding: 0 }}>
          <div className="glyph">
            <Ic n={icon} s={20} />
          </div>
        </div>
        <h1>{title}</h1>
        <p>{text}</p>
        {children && <div className="row">{children}</div>}
      </div>
    </div>
  );
}

export function Studio() {
  useStudio();
  const { route, params } = useRoute();
  const slug = currentSlug();
  const [missing, setMissing] = useState<string | null>(null);
  applyPrefs();
  useEffect(() => {
    installDragDrop();
    installKeyboard();
  }, []);
  // The demo's address shows the seeded workspace; any other is one of yours, from the API.
  useEffect(() => {
    if (slug === WS) return showDemo();
    if (!hasSession()) return location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
    if (live.slug === slug && live.mode !== "error") return;
    setMissing(null);
    void loadWorkspace(slug).then((found) => !found && setMissing(slug));
  }, [slug]);
  useEffect(() => {
    if (slug !== WS && live.mode !== "live") return void (document.title = "dotrix"); // still loading
    let t = ROUTE_NAMES[route] || "Not found";
    if (route === "project") {
      const p = projByKey(params.id);
      if (p) t = `${params.tab ? params.tab[0]!.toUpperCase() + params.tab.slice(1) : "Board"} · ${p.name}`;
    }
    if (route === "member") t = D().members.find((m) => m.id === params.id)?.name ?? t;
    if (route === "team") t = team(params.id)?.name ?? t;
    document.title = `${t} · ${D().ws.name}`;
  });
  if (slug !== WS) {
    if (missing === slug)
      return (
        <Full icon="file-question" title="Workspace not found" text="It doesn't exist, or you aren't a member of it.">
          <button className="btn btn-primary" onClick={() => location.assign("/")}>
            Go to your workspace
          </button>
        </Full>
      );
    if (live.mode === "error")
      return (
        <Full icon="cloud-alert" title="The workspace didn't load" text={live.error || "Try again in a moment."}>
          <button className="btn btn-primary" onClick={() => void loadWorkspace(slug)}>
            <Ic n="refresh-cw" s={14} />
            Try again
          </button>
        </Full>
      );
    if (live.mode !== "live" || live.slug !== slug)
      return (
        <div className="fullstate" style={{ minHeight: "100svh" }} aria-busy="true">
          <span className="faint" style={{ fontSize: 13 }}>
            Loading the workspace…
          </span>
        </div>
      );
  }
  return (
    <>
      <Shell>
        <Screen />
      </Shell>
      <Drawer />
      <ModalLayer />
      <Palette />
    </>
  );
}
