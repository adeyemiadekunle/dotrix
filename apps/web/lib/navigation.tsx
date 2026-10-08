// Navigation for pages and components: links and hooks over TanStack Router (src/router.tsx),
// with the small API the app was written against (Next.js's), so pages take plain hrefs:
// "/w/acme/p/KUN/board?issue=KUN-4".
import { useRouter as useTanStackRouter, useRouterState } from "@tanstack/react-router";
import { useMemo, type AnchorHTMLAttributes, type MouseEvent, type Ref } from "react";

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
  /** Replace the current history entry instead of adding one. */
  replace?: boolean;
  /** Keep the scroll position (filters, tabs); otherwise a new page starts at the top. */
  scroll?: boolean;
  ref?: Ref<HTMLAnchorElement>;
};

/** An in-app link: a real <a> (open in a new tab, copy the address), navigated by the router. */
export function Link({ href, replace, scroll = true, onClick, target, ref, ...props }: LinkProps) {
  const router = useTanStackRouter();
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (target && target !== "_self") ||
      isExternal(href)
    ) {
      return;
    }
    event.preventDefault();
    void router.navigate({ href, replace, resetScroll: scroll });
  }
  return <a ref={ref} href={href} target={target} onClick={handleClick} {...props} />;
}

function isExternal(href: string): boolean {
  // Absolute addresses and the API's own routes (/api/auth/github, /v1/... downloads) leave the app.
  return /^[a-z][a-z\d+.-]*:/i.test(href) || href.startsWith("//") || href.startsWith("/api/") || href.startsWith("/v1/");
}

export interface AppRouter {
  push(href: string, options?: { scroll?: boolean }): void;
  replace(href: string, options?: { scroll?: boolean }): void;
  back(): void;
}

export function useRouter(): AppRouter {
  const router = useTanStackRouter();
  return useMemo(
    () => ({
      push: (href, options) => void router.navigate({ href, resetScroll: options?.scroll ?? true }),
      replace: (href, options) => void router.navigate({ href, replace: true, resetScroll: options?.scroll ?? true }),
      back: () => router.history.back(),
    }),
    [router],
  );
}

export function usePathname(): string {
  return useRouterState({ select: (state) => state.location.pathname });
}

/** The query string as URLSearchParams (read-only: change it with lib/url-state). */
export function useSearchParams(): URLSearchParams {
  const search = useRouterState({ select: (state) => state.location.searchStr });
  return useMemo(() => new URLSearchParams(search), [search]);
}

/** The path's parameters: `workspace`, `project`, `handle`. */
export function useParams<T extends Record<string, string | undefined>>(): T {
  // The deepest route's params include its parents' (a project page has workspace and project).
  const params = useRouterState({
    select: (state): Record<string, string> => state.matches.at(-1)?.params ?? NO_PARAMS,
  });
  return params as T;
}

const NO_PARAMS: Record<string, string> = {};
