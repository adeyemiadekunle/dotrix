"use client";

import { useSyncExternalStore, type ReactNode } from "react";

const subscribe = () => () => {};

/** False on the server and while the page hydrates; true from the first render after. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}

/**
 * Renders `children` only in the browser, once the page has hydrated (`fallback` until then).
 *
 * For content that comes entirely from browser-side queries (every project page). The server
 * can only render its loading state, and a part of the page that hydrates late (inside a
 * Suspense boundary, or while the dev server compiles it) may already see data another
 * component fetched meanwhile: React Query hands it that data during hydration, the markup no
 * longer matches the server's, and React throws a hydration error. Rendering it only after
 * hydration means there's no server markup to match.
 */
export function AfterHydration({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  return useHydrated() ? children : fallback;
}
