// The app's URLs (TanStack Router). A workspace (/w/{workspace}/…) is the shell with the
// screen picked from the path (shell/Studio): one of yours comes from the
// API (data/live.ts, sign-in needed), the demo (/w/dotrix) is seeded in the browser.
import { Navigate, Outlet, createRootRoute, createRoute, createRouter, lazyRouteComponent } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";

import { WS, setRouter } from "./core/nav";
import { startDestination } from "./data/live";
import { NotFoundPage, RootLayout } from "./root";
import { Studio } from "./shell/Studio";
import AuthLayout from "../pages/(auth)/layout";

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** The page's name in the browser tab ("Sign in · dotrix"). */
    title?: string;
  }
  interface Register {
    router: typeof router;
  }
}

const page = (load: () => Promise<{ default: () => ReactNode }>) => lazyRouteComponent(load);

const rootRoute = createRootRoute({ component: RootLayout, notFoundComponent: NotFoundPage });

const auth = createRoute({
  getParentRoute: () => rootRoute,
  id: "auth",
  component: () => (
    <AuthLayout>
      <Outlet />
    </AuthLayout>
  ),
});
const authPage = <P extends string>(path: P, title: string, load: Parameters<typeof page>[0]) =>
  createRoute({ getParentRoute: () => auth, path, staticData: { title }, component: page(load) });
const authRoutes = [
  authPage("/login", "Sign in", () => import("../pages/(auth)/login/page")),
  authPage("/signup", "Create your account", () => import("../pages/(auth)/signup/page")),
  authPage("/signup/finish", "Create your account", () => import("../pages/(auth)/signup/finish/page")),
  authPage("/forgot-password", "Reset your password", () => import("../pages/(auth)/forgot-password/page")),
  authPage("/reset-password", "Choose a new password", () => import("../pages/(auth)/reset-password/page")),
  authPage("/verify-email", "Verify your email", () => import("../pages/(auth)/verify-email/page")),
  authPage("/magic-link", "Sign in", () => import("../pages/(auth)/magic-link/page")),
  authPage("/device", "Sign in a device", () => import("../pages/(auth)/device/page")),
  authPage("/invites/accept", "Join a workspace", () => import("../pages/(auth)/invites/accept/page")),
  createRoute({
    getParentRoute: () => auth,
    path: "/onboarding",
    staticData: { title: "Set up your workspace" },
    component: page(() => import("./screens/Onboarding").then((m) => ({ default: m.Onboarding }))),
  }),
];

/** "/": /login when signed out, /onboarding until verified and set up, else your last (or first) workspace. */
function Start() {
  const [dest, setDest] = useState<string | null>(null);
  useEffect(() => {
    void startDestination().then(setDest);
  }, []);
  if (!dest) return null;
  if (dest === "/login") return <Navigate to="/login" replace />;
  if (dest === "/onboarding") return <Navigate to="/onboarding" replace />;
  return <Navigate to="/w/$ws" params={{ ws: dest.slice(3) }} replace />;
}
function DemoRedirect() {
  const rest = location.pathname.replace(/^\/demo\/?/, "");
  const suffix = rest ? `/${rest}` : "";
  useEffect(() => {
    void router.navigate({ href: `/w/${WS}${suffix}${location.search}`, replace: true });
  }, [suffix]);
  return null;
}
const home = createRoute({ getParentRoute: () => rootRoute, path: "/", component: Start });
const demoRoot = createRoute({ getParentRoute: () => rootRoute, path: "/demo", component: DemoRedirect });
const demoAny = createRoute({ getParentRoute: () => rootRoute, path: "/demo/$", component: DemoRedirect });
const chatUiLab = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dev/chat-ui",
  staticData: { title: "chat/ui lab" },
  component: page(() => import("./screens/ChatUiLab")),
});
const workspace = createRoute({ getParentRoute: () => rootRoute, path: "/w/$ws", component: Studio });
const workspaceAny = createRoute({ getParentRoute: () => rootRoute, path: "/w/$ws/$", component: Studio });

const routeTree = rootRoute.addChildren([auth.addChildren(authRoutes), home, demoRoot, demoAny, chatUiLab, workspace, workspaceAny]);

export const router = createRouter({
  routeTree,
  // The query string stays as written (?task=WEB-109&thread=th1): screens read it with
  // URLSearchParams, not as parsed JSON.
  parseSearch: (search) => Object.fromEntries(new URLSearchParams(search)),
  stringifySearch: (search) => {
    const query = new URLSearchParams(search as Record<string, string>).toString();
    return query ? `?${query}` : "";
  },
  scrollRestoration: true,
});
setRouter(router);
