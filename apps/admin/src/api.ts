// The admin console's API client. The console has its own accounts (POST /v1/ops/*), never the web
// app's session: both tokens live in httpOnly, SameSite=Strict cookies, the refresh cookie scoped to
// /v1/ops/refresh, and browser tabs take turns rotating it (a Web Lock).

type Problem = { detail?: string };
type ApiError = Error & { status?: number };

let refreshing: Promise<string | null> | null = null;

export async function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    const refresh = () => rawCall<void>("/ops/refresh", { method: "POST" }).then(() => "ok");
    return navigator.locks ? navigator.locks.request("dotrix-admin-refresh", refresh) : refresh();
  })()
    .catch(() => null)
    .finally(() => (refreshing = null));
  return (await refreshing) !== null;
}

export async function rawCall<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(`/v1${path}`, {
    method: options.method ?? "GET",
    headers: {
      "X-Requested-With": "dotrix-admin",
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  const data = res.status === 204 ? undefined : await res.json().catch(() => undefined);
  if (!res.ok) {
    const err: ApiError = new Error((data as Problem | undefined)?.detail ?? `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data as T;
}

export async function call<T>(path: string): Promise<T> {
  try {
    return await rawCall<T>(path);
  } catch (e) {
    if ((e as ApiError).status !== 401) throw e;
    if (!(await refreshSession())) throw e;
    return rawCall<T>(path);
  }
}

export type Me = { email: string; name: string };

type StuckRun = { kind: "chat" | "coding"; id: string; status: string; workspace: string; label: string | null; lease_expired_at: string | null };

export type Health = {
  generated_at: string;
  version: string;
  environment: string;
  jobs: string;
  sandbox: string;
  database_ms: number;
  queue_pending: number;
  queue_oldest_seconds: number | null;
  queue_discarded_24h: number;
  worker_last_took_at: string | null;
  runs_running: number;
  runs_queued: number;
  stuck: StuckRun[];
  recovery_required: number;
  interrupted: number;
  sandboxes_warm: number;
  sandboxes_asleep: number;
  runners_online: number;
  runners: number;
  failed_24h: number;
  finished_24h: number;
};

export type Counts = {
  days: number;
  workspaces: number;
  workspaces_new: number;
  workspaces_active: number;
  people: number;
  people_new: number;
  people_active: number;
  projects: number;
  documents: number;
  document_bytes: number;
};

export type Day = {
  day: string;
  chat_runs: number;
  chat_failed: number;
  coding_runs: number;
  coding_failed: number;
  input_tokens: number;
  output_tokens: number;
  coding_cost_usd: number;
  signups: number;
};

type FailureGroup = { key: string; kind: "chat" | "coding" | null; detail: string | null; count: number; last_at: string | null };
export type Failures = { days: number; chat_kinds: FailureGroup[]; chat_models: FailureGroup[]; messages: FailureGroup[] };

export type CodingRow = {
  engine: string;
  location: string;
  turns: number;
  finished: number;
  failed: number;
  prs: number;
  p50_seconds: number | null;
  p95_seconds: number | null;
  tokens: number;
  cost_usd: number;
};

export type WorkspaceRow = {
  id: string;
  name: string;
  slug: string;
  kind: string;
  members: number;
  projects: number;
  created_at: string;
  chat_runs: number;
  coding_runs: number;
  failed: number;
  tokens: number;
  cost_usd: number;
  last_run_at: string | null;
  paused: boolean;
};

export type Run = {
  kind: "chat" | "coding";
  id: string;
  status: string;
  label: string;
  workspace: string | null;
  agent: string | null;
  model: string | null;
  location: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  error: string | null;
  error_kind: string | null;
  automation: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type AuditEvent = {
  id: string;
  action: string;
  workspace: string | null;
  actor_type: string;
  actor_user_id: string | null;
  agent: string | null;
  created_at: string;
};
