import { usePathname, useRouter, useSearchParams } from "@/lib/navigation";
import { useCallback } from "react";

// Slashes and commas are left readable (?file=architecture/overview.md, ?type=story,bug).
function queryString(params: URLSearchParams): string {
  return params.toString().replace(/%2F/gi, "/").replace(/%2C/gi, ",");
}

/**
 * Change several search params in one navigation. Separate updates in a row would race: each
 * starts from the URL before the previous one has landed and would undo it.
 */
export function useSetSearchParams(): (patch: Record<string, string | null>) => void {
  const router = useRouter();
  const pathname = usePathname();
  return useCallback(
    (patch: Record<string, string | null>) => {
      const updated = new URLSearchParams(window.location.search);
      for (const [name, value] of Object.entries(patch)) {
        if (value === null || value === "") updated.delete(name);
        else updated.set(name, value);
      }
      const query = queryString(updated);
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router],
  );
}

/** Read and set a search param without adding history entries or scrolling (filters, open issue). */
export function useSearchParam(name: string): [string | null, (value: string | null) => void] {
  const params = useSearchParams();
  const setParams = useSetSearchParams();
  const set = useCallback((next: string | null) => setParams({ [name]: next }), [name, setParams]);
  return [params.get(name), set];
}
