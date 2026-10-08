// The workspace app (Gr8r's render loop, gr8r-studio/src/shell/render.js): your preferences on
// <html>, the page title, the shell with the screen for the URL, and the overlay layers.
import { useEffect, type ReactNode } from "react";

import { applyPrefs } from "../core/theme";
import { Ic } from "../core/icons";
import { back, go, useRoute, type Route } from "../core/nav";
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
      <Empty icon="hammer" title={ROUTE_NAMES[route] ?? "Coming next"} text="This screen is being brought over from Gr8r Studio." />
    </div>
  );
}

export function Studio() {
  useStudio();
  const { route, params } = useRoute();
  applyPrefs();
  useEffect(() => {
    installDragDrop();
    installKeyboard();
  }, []);
  useEffect(() => {
    let t = ROUTE_NAMES[route] || "Not found";
    if (route === "project") {
      const p = projByKey(params.id);
      if (p) t = `${params.tab ? params.tab[0]!.toUpperCase() + params.tab.slice(1) : "Board"} · ${p.name}`;
    }
    if (route === "member") t = D().members.find((m) => m.id === params.id)?.name ?? t;
    if (route === "team") t = team(params.id)?.name ?? t;
    document.title = `${t} · ${D().ws.name}`;
  });
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
