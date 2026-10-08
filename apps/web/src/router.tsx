// Every page of the app and its URL (TanStack Router). Pages live in pages/ and load when first
// visited. The sign-in guard is optimistic, from a readable marker cookie: the API is what
// checks, and a request it refuses sends you to sign in (lib/api.ts).
import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  redirect,
  type ParsedLocation,
} from "@tanstack/react-router";
import type { ReactNode } from "react";

import { NotFoundPage, RootLayout } from "./root";
import AppLayout from "../pages/(app)/layout";
import ProjectLayout from "../pages/(app)/w/[workspace]/p/[project]/layout";
import SettingsLayout from "../pages/(app)/w/[workspace]/settings/layout";
import AuthLayout from "../pages/(auth)/layout";
import { hasSession, safeNext } from "@/lib/api";

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** The page's name in the browser tab ("Sign in · pmagent"). */
    title?: string;
  }
  interface Register {
    router: typeof router;
  }
}

/** Not signed in: to the sign-in page, then back here. */
function requireSession({ location }: { location: ParsedLocation }) {
  if (hasSession()) return;
  const next = location.pathname === "/" ? "" : `?next=${encodeURIComponent(location.href)}`;
  throw redirect({ href: `/login${next}` });
}

/** Already signed in: the sign-in and sign-up pages go where you were going. */
function skipIfSignedIn({ location }: { location: ParsedLocation }) {
  if (hasSession()) throw redirect({ href: safeNext(new URLSearchParams(location.searchStr).get("next")) });
}

const page = (load: () => Promise<{ default: () => ReactNode }>) => lazyRouteComponent(load);
const goTo = (href: (params: Record<string, string>, search: URLSearchParams) => string) => ({
  beforeLoad: ({ params, location }: { params: Record<string, string>; location: ParsedLocation }) => {
    throw redirect({ href: href(params, new URLSearchParams(location.searchStr)) });
  },
});

const rootRoute = createRootRoute({ component: RootLayout, notFoundComponent: NotFoundPage });

// -- signed out: sign in, sign up, email links ----------------------------------------------

const auth = createRoute({
  getParentRoute: () => rootRoute,
  id: "auth",
  component: () => (
    <AuthLayout>
      <Outlet />
    </AuthLayout>
  ),
});
const authPage = (path: string, title: string, load: Parameters<typeof page>[0], guard?: typeof requireSession) =>
  createRoute({ getParentRoute: () => auth, path, staticData: { title }, beforeLoad: guard, component: page(load) });

const authRoutes = [
  authPage("/login", "Sign in", () => import("../pages/(auth)/login/page"), skipIfSignedIn),
  authPage("/signup", "Create your account", () => import("../pages/(auth)/signup/page"), skipIfSignedIn),
  authPage("/signup/finish", "Create your account", () => import("../pages/(auth)/signup/finish/page")),
  authPage("/forgot-password", "Reset your password", () => import("../pages/(auth)/forgot-password/page")),
  authPage("/reset-password", "Choose a new password", () => import("../pages/(auth)/reset-password/page")),
  authPage("/verify-email", "Verify your email", () => import("../pages/(auth)/verify-email/page")),
  authPage("/magic-link", "Sign in", () => import("../pages/(auth)/magic-link/page")),
  // Signed in: approving a device for the CLI, and joining a workspace.
  authPage("/device", "Sign in a device", () => import("../pages/(auth)/device/page"), requireSession),
  authPage("/invites/accept", "Join a workspace", () => import("../pages/(auth)/invites/accept/page"), requireSession),
];

// -- signed in: the app ---------------------------------------------------------------------

// Browser tab titles; a project page adds the project's key ("Board · KUN · pmagent").
const TITLES: Record<string, string> = {
  "/w/$workspace": "Home",
  "/w/$workspace/overview": "Overview",
  "/w/$workspace/chat": "Chat",
  "/w/$workspace/approvals": "Notifications",
  "/w/$workspace/my-issues": "My issues",
  "/w/$workspace/projects": "Projects",
  "/w/$workspace/projects/new": "New project",
  "/w/$workspace/tasks": "Tasks",
  "/w/$workspace/timeline": "Timeline",
  "/w/$workspace/activity": "Activity",
};
const SETTINGS_TITLES: Record<string, string> = {
  "/": "Settings",
  profile: "Profile",
  appearance: "Appearance",
  notifications: "Notification settings",
  devices: "Devices and tokens",
  calendar: "Calendar",
  members: "Members",
  invites: "Invites",
  permissions: "What members can do",
  agents: "Agents",
  "agents/$handle": "Agent",
  audit: "Audit log",
  github: "GitHub",
};
const PROJECT_TITLES: Record<string, string> = {
  overview: "Overview",
  board: "Board",
  list: "List",
  table: "Table",
  timeline: "Timeline",
  files: "Files",
  knowledge: "Knowledge",
  activity: "Activity",
  settings: "Project settings",
  "settings/agents": "Agents",
  "settings/agents/$handle": "Agent",
};

const app = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  beforeLoad: requireSession,
  component: () => (
    <AppLayout>
      <Outlet />
    </AppLayout>
  ),
});
const appPage = (path: string, load: Parameters<typeof page>[0]) =>
  createRoute({ getParentRoute: () => app, path, staticData: { title: TITLES[path] }, component: page(load) });
const appRedirect = (path: string, to: Parameters<typeof goTo>[0]) =>
  createRoute({ getParentRoute: () => app, path, ...goTo(to) });


const workspaceRoutes = [
  appPage("/", () => import("../pages/(app)/page")),
  appPage("/settings", () => import("../pages/(app)/settings/page")),
  appPage("/w/$workspace", () => import("../pages/(app)/w/[workspace]/page")),
  appPage("/w/$workspace/overview", () => import("../pages/(app)/w/[workspace]/overview/page")),
  appPage("/w/$workspace/chat", () => import("../pages/(app)/w/[workspace]/chat/page")),
  appPage("/w/$workspace/approvals", () => import("../pages/(app)/w/[workspace]/approvals/page")),
  appPage("/w/$workspace/my-issues", () => import("../pages/(app)/w/[workspace]/my-issues/page")),
  appPage("/w/$workspace/projects", () => import("../pages/(app)/w/[workspace]/projects/page")),
  appPage("/w/$workspace/projects/new", () => import("../pages/(app)/w/[workspace]/projects/new/page")),
  appPage("/w/$workspace/tasks", () => import("../pages/(app)/w/[workspace]/tasks/page")),
  appPage("/w/$workspace/timeline", () => import("../pages/(app)/w/[workspace]/timeline/page")),
  appPage("/w/$workspace/activity", () => import("../pages/(app)/w/[workspace]/activity/page")),
  // Agents and the audit log moved into Settings; keep old links working.
  appRedirect("/w/$workspace/agents", (p) => `/w/${p.workspace}/settings/agents`),
  appRedirect("/w/$workspace/agents/$handle", (p) => `/w/${p.workspace}/settings/agents/${p.handle}`),
  appRedirect("/w/$workspace/audit", (p) => `/w/${p.workspace}/settings/audit`),
];

// Settings: a left nav (the layout) around each section.
const settings = createRoute({
  getParentRoute: () => app,
  path: "/w/$workspace/settings",
  component: () => (
    <SettingsLayout>
      <Outlet />
    </SettingsLayout>
  ),
});
const settingsPage = (path: string, load: Parameters<typeof page>[0]) =>
  createRoute({ getParentRoute: () => settings, path, staticData: { title: SETTINGS_TITLES[path] }, component: page(load) });

const settingsRoutes = [
  settingsPage("/", () => import("../pages/(app)/w/[workspace]/settings/page")),
  settingsPage("profile", () => import("../pages/(app)/w/[workspace]/settings/profile/page")),
  settingsPage("appearance", () => import("../pages/(app)/w/[workspace]/settings/appearance/page")),
  settingsPage("notifications", () => import("../pages/(app)/w/[workspace]/settings/notifications/page")),
  settingsPage("devices", () => import("../pages/(app)/w/[workspace]/settings/devices/page")),
  settingsPage("calendar", () => import("../pages/(app)/w/[workspace]/settings/calendar/page")),
  settingsPage("members", () => import("../pages/(app)/w/[workspace]/settings/members/page")),
  settingsPage("invites", () => import("../pages/(app)/w/[workspace]/settings/invites/page")),
  settingsPage("permissions", () => import("../pages/(app)/w/[workspace]/settings/permissions/page")),
  settingsPage("agents", () => import("../pages/(app)/w/[workspace]/settings/agents/page")),
  settingsPage("agents/$handle", () => import("../pages/(app)/w/[workspace]/settings/agents/[handle]/page")),
  settingsPage("audit", () => import("../pages/(app)/w/[workspace]/settings/audit/page")),
  settingsPage("github", () => import("../pages/(app)/w/[workspace]/settings/github/page")),
];

// A project: its header and tabs (the layout) around each view.
const project = createRoute({
  getParentRoute: () => app,
  path: "/w/$workspace/p/$project",
  component: () => (
    <ProjectLayout>
      <Outlet />
    </ProjectLayout>
  ),
});
const projectPage = (path: string, load: Parameters<typeof page>[0]) =>
  createRoute({ getParentRoute: () => project, path, staticData: { title: PROJECT_TITLES[path] }, component: page(load) });
const projectRedirect = (path: string, to: Parameters<typeof goTo>[0]) =>
  createRoute({ getParentRoute: () => project, path, ...goTo(to) });
const P = (p: Record<string, string>) => `/w/${p.workspace}/p/${p.project}`;
const chatAbout = (p: Record<string, string>, search: URLSearchParams) => {
  const thread = search.get("thread");
  return `/w/${p.workspace}/chat?project=${p.project}${thread ? `&thread=${thread}` : ""}`;
};

const projectRoutes = [
  // A project opens on its Overview.
  projectRedirect("/", (p) => `${P(p)}/overview`),
  projectPage("overview", () => import("../pages/(app)/w/[workspace]/p/[project]/overview/page")),
  projectPage("board", () => import("../pages/(app)/w/[workspace]/p/[project]/board/page")),
  projectPage("list", () => import("../pages/(app)/w/[workspace]/p/[project]/list/page")),
  projectPage("table", () => import("../pages/(app)/w/[workspace]/p/[project]/table/page")),
  projectPage("timeline", () => import("../pages/(app)/w/[workspace]/p/[project]/timeline/page")),
  projectPage("files", () => import("../pages/(app)/w/[workspace]/p/[project]/files/page")),
  projectPage("knowledge", () => import("../pages/(app)/w/[workspace]/p/[project]/knowledge/page")),
  projectPage("activity", () => import("../pages/(app)/w/[workspace]/p/[project]/activity/page")),
  projectPage("settings", () => import("../pages/(app)/w/[workspace]/p/[project]/settings/page")),
  projectPage("settings/agents", () => import("../pages/(app)/w/[workspace]/p/[project]/settings/agents/page")),
  projectPage(
    "settings/agents/$handle",
    () => import("../pages/(app)/w/[workspace]/p/[project]/settings/agents/[handle]/page"),
  ),
  // Renamed or moved tabs; keep old links working.
  projectRedirect("backlog", (p) => `${P(p)}/list`),
  projectRedirect("docs", (p) => `${P(p)}/files`),
  projectRedirect("chat", chatAbout),
  projectRedirect("briefing", chatAbout),
];

const routeTree = rootRoute.addChildren([
  auth.addChildren(authRoutes),
  app.addChildren([
    ...workspaceRoutes,
    settings.addChildren(settingsRoutes),
    project.addChildren(projectRoutes),
  ]),
]);

export const router = createRouter({
  routeTree,
  // The query string stays as written (?type=story,bug&issue=KUN-4): pages read it with
  // URLSearchParams (lib/navigation, lib/url-state), not as parsed JSON.
  parseSearch: (search) => Object.fromEntries(new URLSearchParams(search)),
  stringifySearch: (search) => {
    const query = new URLSearchParams(search as Record<string, string>).toString();
    return query ? `?${query}` : "";
  },
  scrollRestoration: true,
  defaultPreload: "intent",
});
