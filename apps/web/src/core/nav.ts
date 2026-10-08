// Gr8r's go(route, params) as URLs (dotrix's /w/{workspace}/… scheme, so the API can be wired in
// without changing addresses). Screens ask where they are with useRoute().
import { useRouterState, type AnyRouter } from "@tanstack/react-router";

export const WS = "dotrix"; // the demo (seeded) workspace's slug

/** The workspace in the address (/w/{slug}/…), or the demo's. */
export function currentSlug(): string {
  return (typeof location !== "undefined" && location.pathname.match(/^\/w\/([^/]+)/)?.[1]) || WS;
}

export type Route =
  | "home"
  | "inbox"
  | "mytasks"
  | "favorites"
  | "notifications"
  | "search"
  | "overview"
  | "projects"
  | "project"
  | "tasks"
  | "calendar"
  | "timeline"
  | "members"
  | "member"
  | "teams"
  | "team"
  | "activity"
  | "settings"
  | "archive"
  | "chat"
  | "system"
  | "states";

export interface Params {
  id?: string; // a project key, member, or team id
  tab?: string; // a project's view
  sec?: string; // a settings section
  [k: string]: string | undefined;
}

const SIMPLE: Partial<Record<Route, string>> = {
  inbox: "inbox",
  mytasks: "my-tasks",
  favorites: "favorites",
  notifications: "notifications",
  search: "search",
  overview: "overview",
  projects: "projects",
  tasks: "tasks",
  calendar: "calendar",
  timeline: "timeline",
  members: "members",
  teams: "teams",
  activity: "activity",
  archive: "archive",
  chat: "chat",
  system: "design-system",
  states: "system-states",
};

export function href(route: Route, params: Params = {}): string {
  const base = `/w/${currentSlug()}`;
  if (route === "home") return base;
  if (route === "project") return `${base}/p/${params.id}/${params.tab || "board"}`;
  if (route === "member") return `${base}/members/${params.id}`;
  if (route === "team") return `${base}/teams/${params.id}`;
  if (route === "settings") return `${base}/settings${params.sec ? `/${params.sec}` : ""}`;
  return `${base}/${SIMPLE[route] ?? ""}`;
}

/** Where we are, as Gr8r's route and params. */
export function routeOf(pathname: string): { route: Route | "notfound"; params: Params } {
  const m = pathname.match(/^\/w\/[^/]+(?:\/(.*))?$/);
  if (!m) return { route: "notfound", params: {} };
  const [first, second, third] = (m[1] ?? "").split("/").filter(Boolean);
  if (!first) return { route: "home", params: {} };
  if (first === "p" && second) return { route: "project", params: { id: second, tab: third || "board" } };
  if (first === "members" && second) return { route: "member", params: { id: second } };
  if (first === "teams" && second) return { route: "team", params: { id: second } };
  if (first === "settings") return { route: "settings", params: { sec: second } };
  const found = (Object.entries(SIMPLE) as [Route, string][]).find(([, seg]) => seg === first);
  return found && !second ? { route: found[0], params: {} } : { route: "notfound", params: {} };
}

export function useRoute() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const search = useRouterState({ select: (s) => s.location.searchStr });
  return { ...routeOf(pathname), search: new URLSearchParams(search) };
}

let router: AnyRouter | null = null;
export function setRouter(r: AnyRouter) {
  router = r;
}
/** Go somewhere (Gr8r's go()); `replace` keeps the history entry, `search` sets the query. */
export function go(route: Route, params: Params = {}, opt: { replace?: boolean; search?: string } = {}) {
  void router?.navigate({ href: href(route, params) + (opt.search ? `?${opt.search}` : ""), replace: opt.replace });
}
export function back() {
  router?.history.back();
}
