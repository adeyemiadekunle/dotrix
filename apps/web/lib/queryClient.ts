// The app's QueryClient, shared with module code that can't call useQueryClient — the
// live.ts write path invalidates these caches after its API calls so screens that read
// hooks stay fresh while the rest still rides the store.
import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./api";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Retrying won't fix a 4xx (not found, forbidden, invalid input).
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

/** live.ts writes go through the store's senders; refreshing every mounted query keeps the
 *  hook-read screens in step with them until the kit moves to mutations of its own. */
export function invalidateLiveQueries() {
  void queryClient.invalidateQueries();
}
