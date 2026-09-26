// Typed client for the pmagent API (apps/backend), used by web and desktop.
//
// `schema.ts` is generated from `openapi.json`, which is exported from the backend.
// Never edit either by hand: run `pnpm openapi` at the repo root after changing the API.
import createFetchClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema.js";

export type { components, operations, paths } from "./schema.js";
export type Schemas = components["schemas"];
/** RFC 9457 error body. Switch on `type`, not `detail`. */
export type ProblemDetail = Schemas["ProblemDetail"];

export interface ClientOptions {
  baseUrl: string;
  /** Returns the current access or API token; called on every request. */
  getToken?: () => string | undefined | Promise<string | undefined>;
}

export function createClient({ baseUrl, getToken }: ClientOptions) {
  const client = createFetchClient<paths>({ baseUrl });
  if (getToken) {
    const auth: Middleware = {
      async onRequest({ request }) {
        const token = await getToken();
        if (token) request.headers.set("Authorization", `Bearer ${token}`);
        return request;
      },
    };
    client.use(auth);
  }
  return client;
}

export type PmagentClient = ReturnType<typeof createClient>;
