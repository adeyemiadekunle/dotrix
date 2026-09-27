"use client";

// The browser's API client. Calls go to this app's /api/v1/* proxy, which adds the session's
// token, so there is nothing secret here.
import { createClient, type ProblemDetail, type Schemas } from "@pmagent/api-client";

export type { Schemas };

export const api = createClient({ baseUrl: "/api" });

// A session that can't be refreshed is over: send the user to sign in again.
api.use({
  onResponse({ response }) {
    if (response.status === 401 && typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
      const next = `${location.pathname}${location.search}`;
      location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    return response;
  },
});

/** Thrown by `unwrap` so TanStack Query sees failures; carries the problem+json body. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem?: ProblemDetail,
  ) {
    super(problemMessage(problem) ?? `Request failed (${status})`);
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** openapi-fetch returns `{ data, error }`; turn an error into a thrown ApiError. */
export async function unwrap<T>(request: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await request;
  if (error !== undefined || !response.ok) throw new ApiError(response.status, error as ProblemDetail | undefined);
  return data as T;
}

/** A sentence for the user: field errors on 422, otherwise the problem's detail. */
export function problemMessage(problem: ProblemDetail | undefined): string | undefined {
  if (!problem) return undefined;
  const first = problem.errors?.[0] as { loc?: unknown[]; msg?: string } | undefined;
  if (first?.msg) {
    const field = first.loc?.at(-1);
    const label = typeof field === "string" ? field.replaceAll("_", " ") : undefined;
    const msg = first.msg.replace(/^Value error, /, "");
    return label ? `${label[0]!.toUpperCase()}${label.slice(1)}: ${msg}` : msg;
  }
  return problem.detail;
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Something went wrong. Try again.";
}

/** POST JSON to one of this app's own auth routes (/api/auth/*). */
export async function authPost(path: string, body?: unknown): Promise<Response> {
  const response = await fetch(`/api/auth/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = (await response.json().catch(() => undefined)) as ProblemDetail | undefined;
    throw new ApiError(response.status, problem);
  }
  return response;
}

/** Only same-site paths are followed after sign-in, never another origin. */
export function safeNext(next: string | null | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}
