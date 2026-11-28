import type { AdminAlerts, AuditEvent, CodingRow, Counts, Day, Failures, GrowthSnapshot, Health, ModelRow, Page, Run } from "./api";

const now = Date.now();
const minute = 60_000;
const day = 24 * 60 * minute;
const ago = (minutes: number) => new Date(now - minutes * minute).toISOString();

const health: Health = {
  generated_at: ago(0),
  version: "0.4.0",
  api_revision: "sample-api",
  operations: {
    worker_revision: "sample-worker",
    worker_heartbeat_at: ago(0.5),
    email_last_accepted_at: ago(12),
    email_retries_today: 1,
    email_permanent_failures_today: 0,
    first_nova_event_samples_today: 31,
    first_nova_event_mean_ms_today: 840,
  },
  environment: "demo",
  jobs: "worker",
  sandbox: "docker-cloud",
  database_ms: 18,
  queue_pending: 2,
  queue_oldest_seconds: 11,
  queue_discarded_24h: 0,
  worker_last_took_at: ago(0.1),
  last_queue_wait_ms: 320,
  runs_running: 3,
  runs_queued: 2,
  stuck: [],
  recovery_required: 0,
  interrupted: 0,
  sandboxes_warm: 2,
  sandboxes_asleep: 4,
  runners_online: 3,
  runners: 4,
  failed_24h: 2,
  finished_24h: 41,
  dependencies: [
    { id: "database", state: "ok", detail: "PostgreSQL reachable", latency_ms: 18 },
    { id: "redis", state: "ok", detail: "Queue reachable", latency_ms: 5 },
    { id: "email", state: "degraded", detail: "A delivery is waiting to retry", latency_ms: null },
  ],
  workers_alive: 2,
  notification_emails_waiting: 1,
  notification_email_oldest_seconds: 60,
  automation_events_waiting: 0,
  coding_slots: 8,
  coding_running_cloud: 2,
};

const alerts: AdminAlerts = {
  open: [{ key: "email-retry", summary: "Transactional email is waiting to retry", opened_at: ago(4), resolved_at: null, notified: false }],
  resolved: [],
};

const counts: Counts = {
  days: 7,
  workspaces: 12,
  workspaces_new: 2,
  workspaces_active: 8,
  people: 36,
  people_new: 5,
  people_active: 24,
  projects: 19,
  documents: 47,
  document_bytes: 54 * 1024 * 1024,
};

const codingEngine = "claude-code";

const growth: GrowthSnapshot = {
  traffic: { status: "ready", page_views: 1_824, visits: 1_206 },
  downloads: { status: "ready", desktop: 394, cli: 281 },
};

const runs: Run[] = Array.from({ length: 36 }, (_, index) => {
  const kind = index % 2 === 0 ? "chat" : "coding";
  const failed = index % 9 === 2;
  const workspace = index % 3 === 0 ? "field-notes" : "harbor-studio";
  const minutes = index * 18 + 3;
  return {
    kind,
    id: `sample-run-${index + 1}`,
    label: kind === "chat" ? "Launch planning" : "HBR-24 · Update release checklist",
    workspace,
    status: failed ? "failed" : index < 2 ? "running" : kind === "chat" ? "completed" : "pr_opened",
    agent: kind === "chat" ? "Nova" : codingEngine,
    model: kind === "chat" ? "gpt-5-mini" : "claude-sonnet-4-6",
    location: kind === "chat" ? null : index % 3 === 0 ? "local" : "cloud",
    input_tokens: 2_160 + index * 43,
    output_tokens: 360 + index * 17,
    cost_usd: kind === "chat" ? 0.012 : 0.079,
    error: failed ? "Provider rate limit exceeded" : null,
    error_kind: failed ? "rate_limit" : null,
    automation: index % 8 === 0,
    created_at: ago(minutes),
    started_at: ago(minutes - 1),
    finished_at: index < 2 ? null : ago(minutes - 2),
  };
});

const audit: AuditEvent[] = Array.from({ length: 32 }, (_, index) => {
  const actions = ["coding.run_finished", "agent_run.finished", "project.created", "member.joined"];
  const actor = index % actions.length < 2 ? "agent" : "user";
  return {
    id: `sample-event-${index + 1}`,
    action: actions[index % actions.length],
    workspace: index % 3 === 0 ? "field-notes" : "harbor-studio",
    actor_type: actor,
    actor_user_id: actor === "user" ? "sample-person" : null,
    agent: actor === "agent" ? (index % actions.length === 0 ? "Kai" : "Nova") : null,
    created_at: ago(index * 95 + 4),
  };
});

function trends(days: number): Day[] {
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(now - (days - index - 1) * day).toISOString().slice(0, 10);
    const variation = Number(date.slice(-2)) % 7;
    return {
      day: date,
      chat_runs: 22 + variation * 3,
      chat_failed: variation % 3,
      coding_runs: 7 + variation * 2,
      coding_failed: variation % 2,
      input_tokens: 64_000 + variation * 5_000,
      output_tokens: 12_000 + variation * 800,
      chat_cost_usd: 0.36 + variation * 0.07,
      coding_cost_usd: 0.82 + variation * 0.16,
      unpriced_chat_runs: 0,
      signups: variation % 3,
    };
  });
}

function failures(days: number): Failures {
  const rateLimit = { kind: "chat" as const, count: days + 2, last_at: ago(39), detail: "Provider rate limit exceeded" };
  return {
    days,
    chat_kinds: [{ ...rateLimit, key: "rate_limit" }],
    chat_models: [{ ...rateLimit, key: "gpt-5-mini" }],
    messages: [
      { ...rateLimit, key: "Provider rate limit exceeded" },
      { kind: "coding", key: "Sandbox startup timed out", detail: "Sandbox startup timed out", count: Math.ceil(days / 4), last_at: ago(145) },
    ],
  };
}

function coding(days: number): CodingRow[] {
  return [
    {
      engine: codingEngine,
      location: "cloud",
      turns: days * 5,
      finished: days * 4,
      failed: days,
      prs: days * 2,
      p50_seconds: 84,
      p95_seconds: 165,
      tokens: days * 18_400,
      cost_usd: days * 0.82,
    },
    {
      engine: "codex",
      location: "local",
      turns: days * 3,
      finished: days * 3,
      failed: 0,
      prs: days,
      p50_seconds: 63,
      p95_seconds: 122,
      tokens: days * 7_200,
      cost_usd: days * 0.28,
    },
  ];
}

function models(days: number): ModelRow[] {
  return [
    {
      model: "gpt-5-mini",
      provider: "openai",
      chat_runs: days * 22,
      coding_runs: 0,
      failed: days,
      limit_stops: 0,
      input_tokens: days * 48_000,
      output_tokens: days * 9_600,
      cost_usd: days * 0.42,
      cost_is_estimate: true,
    },
    {
      model: "claude-sonnet-4-6",
      provider: "anthropic",
      chat_runs: 0,
      coding_runs: days * 5,
      failed: Math.ceil(days / 4),
      limit_stops: 1,
      input_tokens: days * 18_400,
      output_tokens: days * 3_800,
      cost_usd: days * 0.82,
      cost_is_estimate: false,
    },
  ];
}

function paginate<T>(rows: T[], params: URLSearchParams): Page<T> {
  const offset = Number(params.get("offset") ?? 0);
  const limit = Number(params.get("limit") ?? 25);
  return { items: rows.slice(offset, offset + limit), total: rows.length };
}

export function readDemo(path: string) {
  const { pathname, searchParams } = new URL(path, "http://localhost");
  const days = Math.min(90, Math.max(1, Number(searchParams.get("days")) || 7));
  switch (pathname) {
    case "/admin/observe/health":
      return health;
    case "/admin/observe/alerts":
      return alerts;
    case "/admin/observe/counts":
      return counts;
    case "/admin/observe/trends":
      return trends(days);
    case "/admin/observe/growth":
      return growth;
    case "/admin/observe/failures":
      return failures(days);
    case "/admin/observe/coding":
      return coding(days);
    case "/admin/observe/models":
      return models(days);
    case "/admin/observe/runs": {
      const kind = searchParams.get("kind");
      const failed = searchParams.get("failed") === "true";
      return paginate(
        runs.filter((run) => (!kind || run.kind === kind) && (!failed || run.status === "failed")),
        searchParams,
      );
    }
    case "/admin/audit": {
      const action = searchParams.get("action") ?? "";
      const workspace = searchParams.get("workspace");
      const actor = searchParams.get("actor_type");
      const since = searchParams.get("since");
      const until = searchParams.get("until");
      const matches = audit.filter((event) => {
        const date = event.created_at.slice(0, 10);
        return (
          event.action.startsWith(action) &&
          (!workspace || workspace === event.workspace) &&
          (!actor || actor === event.actor_type) &&
          (!since || date >= since) &&
          (!until || date <= until)
        );
      });
      return paginate(matches, searchParams);
    }
    default:
      throw new Error(`No sample data for ${pathname}.`);
  }
}
