// The browser's API client. The API is on this app's own origin (/v1/*, and the session routes
// under /api/auth/*): the session lives in httpOnly cookies the API sets, so nothing here is
// secret. Every request carries X-Requested-With, which the API requires on cookie-authenticated
// changes (a page on another site can't send it). An expired session is refreshed once and the
// request retried, so pages never handle token expiry.
import { createClient, type ProblemDetail, type Schemas } from "@dotrix/api-client";
import { useQuery } from "@tanstack/react-query";

export type { Schemas };

const WEB_HEADER = { "X-Requested-With": "dotrix-web" };

/** Whether this browser has a session (a readable marker cookie; the API is what checks). */
export function hasSession(): boolean {
  return typeof document !== "undefined" && /(?:^|;\s*)dx_session=/.test(document.cookie);
}

const REFRESHED_AT = "dotrix.refreshedAt";

/**
 * Trade the refresh cookie for a new session. The API rotates refresh tokens and signs a session
 * out if an old one comes back, so only one refresh runs at a time in this browser (a Web Lock
 * shared by its tabs), and a request that started before another tab refreshed just retries.
 */
async function refreshSession(sentAt: number): Promise<boolean> {
  const run = async () => {
    const last = Number(localStorage.getItem(REFRESHED_AT) ?? 0);
    if (last > sentAt) return true; // refreshed meanwhile: the cookies are already new
    const response = await fetch("/api/auth/refresh", { method: "POST", headers: WEB_HEADER });
    if (!response.ok) return false;
    try {
      localStorage.setItem(REFRESHED_AT, String(Date.now()));
    } catch {
      // only an optimisation
    }
    return true;
  };
  return navigator.locks ? navigator.locks.request("dotrix-session-refresh", run) : run();
}

function toSignIn() {
  if (location.pathname.startsWith("/login")) return;
  const next = `${location.pathname}${location.search}`;
  location.assign(`/login?next=${encodeURIComponent(next)}`);
}

/**
 * fetch() for this app's API: adds the header, refreshes an expired session once and retries,
 * and sends you to sign in when the session is over. Use it for requests the typed client can't
 * make (uploads with progress aside: FormData bodies, file contents).
 */
export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const request = new Request(input, init);
  for (const [name, value] of Object.entries(WEB_HEADER)) request.headers.set(name, value);
  const retry = request.clone();
  const sentAt = Date.now();
  const response = await fetch(request);
  if (response.status !== 401) return response;
  if (!(await refreshSession(sentAt))) {
    toSignIn();
    return response;
  }
  const again = await fetch(retry);
  if (again.status === 401) toSignIn();
  return again;
}

/** Before opening an EventSource (it can't refresh on its own): make sure the session is current. */
export async function ensureSession(): Promise<void> {
  await apiFetch("/v1/me").catch(() => undefined);
}

export const api = createClient({ baseUrl: "", fetch: (request) => apiFetch(request) });

/** Thrown by `unwrap` so TanStack Query sees failures; carries the problem+json body. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem?: ProblemDetail,
  ) {
    super(problemMessage(problem) ?? (status === 404 || status >= 500 ? `the server isn't responding (${status})` : `request failed (${status})`));
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

/** POST JSON to one of the session routes (/api/auth/*: sign in, sign up, sign out). */
export async function authPost(path: string, body?: unknown): Promise<Response> {
  const response = await fetch(`/api/auth/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...WEB_HEADER },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const problem = (await response.json().catch(() => undefined)) as ProblemDetail | undefined;
    throw new ApiError(response.status, problem);
  }
  return response;
}

/** Which other ways to sign in the API has set up (none while it's loading or unreachable). */
export function useAuthProviders(): { github: boolean } {
  const providers = useQuery({
    queryKey: ["auth-providers"],
    queryFn: () => unwrap(api.GET("/v1/auth/providers")),
    staleTime: 5 * 60_000,
  });
  return { github: providers.data?.github ?? false };
}

/** Only same-site paths are followed after sign-in, never another origin. */
export function safeNext(next: string | null | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}
