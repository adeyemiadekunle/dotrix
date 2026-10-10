// Typed client for the dotrix API (apps/backend), used by web and desktop.
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
  /** Sends each request (the web app's adds its session handling); `globalThis.fetch` by default. */
  fetch?: (request: Request) => Promise<Response>;
}

export function createClient({ baseUrl, getToken, fetch }: ClientOptions) {
  const client = createFetchClient<paths>({ baseUrl, ...(fetch ? { fetch } : {}) });
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

export type DotrixClient = ReturnType<typeof createClient>;
