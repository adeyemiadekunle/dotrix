// The app's URLs (TanStack Router). The workspace (/w/{workspace}/…) is Gr8r's shell with the
// screen picked from the path (shell/Studio, like Gr8r's renderPage); it runs on seeded data, so
// no sign-in is needed until the API is wired. The sign-in pages are the API-backed ones.
import { Navigate, Outlet, createRootRoute, createRoute, createRouter, lazyRouteComponent } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { WS, setRouter } from "./core/nav";
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
const authPage = (path: string, title: string, load: Parameters<typeof page>[0]) =>
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
  createRoute({ getParentRoute: () => auth, path: "/onboarding", staticData: { title: "Set up your workspace" }, component: page(() => import("./screens/Onboarding").then((m) => ({ default: m.Onboarding }))) }),
];

const home = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => <Navigate to="/w/$ws" params={{ ws: WS }} replace />,
});
const workspace = createRoute({ getParentRoute: () => rootRoute, path: "/w/$ws", component: Studio });
const workspaceAny = createRoute({ getParentRoute: () => rootRoute, path: "/w/$ws/$", component: Studio });

const routeTree = rootRoute.addChildren([auth.addChildren(authRoutes), home, workspace, workspaceAny]);

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
