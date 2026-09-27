"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/** Read and set search params without adding history entries or scrolling (filters, open issue). */
export function useSearchParam(name: string): [string | null, (value: string | null) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const value = params.get(name);
  const set = useCallback(
    (next: string | null) => {
      const updated = new URLSearchParams(window.location.search);
      if (next === null || next === "") updated.delete(name);
      else updated.set(name, next);
      const query = updated.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [name, pathname, router],
  );
  return [value, set];
}
