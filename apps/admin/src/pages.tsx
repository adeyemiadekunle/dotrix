// The console's pages: Overview (is it working), Runs, Failures, Coding, Workspaces, Audit log.
// Everything is read-only, across every workspace, and never shows what people wrote.
import {
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  DatabaseIcon,
  DesktopTowerIcon,
  GearSixIcon,
  QueueIcon,
  WarningCircleIcon,
  WarningIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { call, type AuditEvent, type CodingRow, type Counts, type Day, type Failures, type Health, type Run, type WorkspaceRow } from "./api";
import {
  ago,
  bytes,
  Card,
  Columns,
  compact,
  DAYS,
  duration,
  Empty,
  Failed,
  Loading,
  Meter,
  num,
  PageHead,
  pct,
  Pill,
  Segmented,
  Status,
  Tile,
  usd,
  useTick,
  words,
  when,
  type Tone,
} from "./ui";

const REFRESH = 15_000;
const OK_COLOR = "var(--chart-ok)";
const BAD_COLOR = "var(--chart-bad)";

// ---------------------------------------------------------------- Overview

type Check = { id: string; label: string; tone: Tone; value: ReactNode; detail: ReactNode; icon: ReactNode };

function checks(h: Health, now: number): Check[] {
  const queueTone: Tone = h.queue_oldest_seconds == null ? "good" : h.queue_oldest_seconds > 300 ? "bad" : h.queue_oldest_seconds > 60 ? "warn" : "good";
  const workerIdle = h.worker_last_took_at ? (now - new Date(h.worker_last_took_at).getTime()) / 1000 : null;
  // A queue with work in it and no worker taking from it is the outage to catch.
  const workerTone: Tone = h.jobs !== "worker" ? "muted" : h.queue_pending > 0 && (workerIdle == null || workerIdle > 120) ? "bad" : "good";
  return [
    {
      id: "db",
      label: "Database",
      icon: <DatabaseIcon size={18} />,
      tone: h.database_ms > 250 ? "warn" : "good",
      value: `${h.database_ms} ms`,
      detail: "to answer a query",
    },
    {
      id: "queue",
      label: "Run queue",
      icon: <QueueIcon size={18} />,
      tone: queueTone,
      value: h.queue_pending ? `${h.queue_pending} waiting` : "Empty",
      detail: h.queue_oldest_seconds != null ? `oldest for ${duration(h.queue_oldest_seconds)}` : `${h.queue_discarded_24h} given up in 24h`,
    },
    {
      id: "worker",
      label: "Workers",
      icon: <GearSixIcon size={18} />,
      tone: workerTone,
      value: h.jobs === "worker" ? ago(h.worker_last_took_at, now) : h.jobs,
      detail: h.jobs === "worker" ? "last took a run" : "no worker queue in this deployment",
    },
    {
      id: "stuck",
      label: "Stuck runs",
      icon: <WarningIcon size={18} />,
      tone: h.stuck.length ? "bad" : "good",
      value: h.stuck.length || "None",
      detail: "active, with a lapsed lease",
    },
    {
      id: "recovery",
      label: "Needs recovery",
      icon: <ClockCounterClockwiseIcon size={18} />,
      tone: h.recovery_required ? "warn" : "good",
      value: h.recovery_required || "None",
      detail: `coding turns · ${h.interrupted} chat runs interrupted`,
    },
    {
      id: "runners",
      label: "Runners",
      icon: <DesktopTowerIcon size={18} />,
      tone: "muted",
      value: `${h.runners_online} of ${h.runners} online`,
      detail: `${h.sandboxes_warm} sandboxes warm · ${h.sandboxes_asleep} asleep`,
    },
  ];
}

const TONE_ICON: Record<Tone, ReactNode> = {
  good: <CheckCircleIcon size={16} weight="fill" />,
  warn: <WarningCircleIcon size={16} weight="fill" />,
  bad: <XCircleIcon size={16} weight="fill" />,
  info: <CheckCircleIcon size={16} weight="fill" />,
  muted: <CheckCircleIcon size={16} />,
};

export function Overview({ go }: { go: (page: string) => void }) {
  const now = useTick();
  const [days, setDays] = useState(14);
  const health = useQuery({ queryKey: ["health"], queryFn: () => call<Health>("/ops/observe/health"), refetchInterval: REFRESH });
  const counts = useQuery({ queryKey: ["counts"], queryFn: () => call<Counts>("/ops/observe/counts?days=7"), refetchInterval: 60_000 });
  const trends = useQuery({ queryKey: ["trends", days], queryFn: () => call<Day[]>(`/ops/observe/trends?days=${days}`), refetchInterval: 60_000 });

  const list = health.data ? checks(health.data, now) : [];
  const worst: Tone = list.some((c) => c.tone === "bad") ? "bad" : list.some((c) => c.tone === "warn") ? "warn" : "good";
  const h = health.data;
  const t = trends.data ?? [];
  const week = t.slice(-7);
  const tokens7 = week.reduce((s, d) => s + d.input_tokens + d.output_tokens, 0);
  const cost7 = week.reduce((s, d) => s + d.coding_cost_usd, 0);

  return (
    <>
      <PageHead
        title="Overview"
        sub={
          h ? (
            <>
              {h.environment} · v{h.version} · jobs {h.jobs} · sandbox {h.sandbox} · updated {ago(h.generated_at, now)}
            </>
          ) : (
            "Is dotrix working, and how much is it used"
          )
        }
      />
      {health.isError ? (
        <Failed error={health.error} />
      ) : !h ? (
        <Loading what="Checking the deployment" />
      ) : (
        <>
          <div className={`banner ${worst}`}>
            {TONE_ICON[worst]}
            <b>{worst === "good" ? "Everything is working" : worst === "warn" ? "Working, with something to watch" : "Something needs attention"}</b>
            <span>
              {h.runs_running} running · {h.runs_queued} queued · {h.failed_24h} failed of {h.finished_24h} finished in 24h
            </span>
          </div>
          <div className="hcs">
            {list.map((c) => (
              <div key={c.id} className={`hc ${c.tone}`}>
                <span className="hc-icon">{c.icon}</span>
                <span className="hc-label">
                  {c.label}
                  <span className={`hc-state ${c.tone}`} aria-label={c.tone}>
                    {TONE_ICON[c.tone]}
                  </span>
                </span>
                <span className="hc-value">{c.value}</span>
                <span className="hc-detail">{c.detail}</span>
              </div>
            ))}
          </div>
          {h.stuck.length > 0 && (
            <Card title="Stuck runs" aside={<span className="muted">The worker's sweep should pick these up within about two minutes</span>} flush>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Kind</th>
                      <th>Workspace</th>
                      <th>Run</th>
                      <th>Status</th>
                      <th className="r">Lease lapsed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {h.stuck.map((s) => (
                      <tr key={s.id}>
                        <td>{s.kind}</td>
                        <td className="mono">{s.workspace}</td>
                        <td className="mono">{s.label ?? s.id.slice(0, 8)}</td>
                        <td>
                          <Status status={s.status} />
                        </td>
                        <td className="r">{ago(s.lease_expired_at, now)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}

      <div className="tiles">
        <Tile
          label="Failure rate, 24h"
          value={h ? pct(h.failed_24h, h.finished_24h) : "—"}
          foot={h ? `${h.failed_24h} of ${h.finished_24h} runs` : undefined}
          tone={h && h.finished_24h && h.failed_24h / h.finished_24h > 0.1 ? "bad" : undefined}
        />
        <Tile
          label="Active people, 7d"
          value={counts.data ? num(counts.data.people_active) : "—"}
          foot={counts.data ? `of ${num(counts.data.people)} · ${counts.data.people_new} new` : undefined}
        />
        <Tile
          label="Active workspaces, 7d"
          value={counts.data ? num(counts.data.workspaces_active) : "—"}
          foot={counts.data ? `of ${num(counts.data.workspaces)} · ${counts.data.workspaces_new} new` : undefined}
        />
        <Tile label="Tokens, 7d" value={trends.data ? compact(tokens7) : "—"} foot="on people's own keys" />
        <Tile label="Coding cost, 7d" value={trends.data ? usd(cost7) : "—"} foot="as the engines report it" />
        <Tile
          label="Stored"
          value={counts.data ? bytes(counts.data.document_bytes) : "—"}
          foot={counts.data ? `${num(counts.data.documents)} documents · ${num(counts.data.projects)} projects` : undefined}
        />
      </div>

      <div className="grid-2">
        <Card title="Runs per day" aside={<Segmented label="Window" value={days} options={DAYS} onChange={setDays} />}>
          {trends.isError ? (
            <Failed error={trends.error} />
          ) : !trends.data ? (
            <Loading />
          ) : (
            <Columns
              days={t.map((d) => d.day)}
              series={[
                { key: "ok", label: "Finished or running", color: OK_COLOR },
                { key: "failed", label: "Failed", color: BAD_COLOR },
              ]}
              value={(i, key) =>
                key === "failed" ? t[i].chat_failed + t[i].coding_failed : t[i].chat_runs + t[i].coding_runs - t[i].chat_failed - t[i].coding_failed
              }
            />
          )}
          <p className="note">
            Chat runs and coding turns started each day (UTC).{" "}
            <button type="button" className="link" onClick={() => go("failures")}>
              See what failed
            </button>
          </p>
        </Card>
        <Card title="Tokens per day">
          {!trends.data ? (
            <Loading />
          ) : (
            <Columns
              days={t.map((d) => d.day)}
              series={[{ key: "tokens", label: "Tokens", color: OK_COLOR }]}
              value={(i) => t[i].input_tokens + t[i].output_tokens}
            />
          )}
          <p className="note">Input and output tokens of the runs started each day, chat and coding together.</p>
        </Card>
      </div>
      <Card title="Sign-ups per day">
        {!trends.data ? (
          <Loading />
        ) : (
          <Columns height={120} days={t.map((d) => d.day)} series={[{ key: "signups", label: "Sign-ups", color: OK_COLOR }]} value={(i) => t[i].signups} />
        )}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- Runs

const PAGE = 50;

export function Runs() {
  const now = useTick();
  const [kind, setKind] = useState<"all" | "chat" | "coding">("all");
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const q = useInfiniteQuery({
    queryKey: ["runs", kind, failed],
    initialPageParam: null as { at: string; id: string } | null,
    queryFn: ({ pageParam }) =>
      call<Run[]>(
        `/ops/observe/runs?limit=${PAGE}${kind === "all" ? "" : `&kind=${kind}`}${failed ? "&failed=true" : ""}${
          pageParam ? `&before=${encodeURIComponent(pageParam.at)}&before_id=${pageParam.id}` : ""
        }`,
      ),
    getNextPageParam: (last) => (last.length === PAGE ? { at: last[last.length - 1].created_at, id: last[last.length - 1].id } : null),
    refetchInterval: REFRESH,
  });
  const runs = q.data?.pages.flat() ?? [];

  return (
    <>
      <PageHead title="Runs" sub="Every chat run and coding turn, newest first. Named by workspace, project and issue, never by what was asked.">
        <Segmented
          label="Kind"
          value={kind}
          options={[
            { value: "all", label: "All" },
            { value: "chat", label: "Chat" },
            { value: "coding", label: "Coding" },
          ]}
          onChange={setKind}
        />
        <Segmented
          label="Status"
          value={failed ? "failed" : "any"}
          options={[
            { value: "any", label: "Any status" },
            { value: "failed", label: "Failed" },
          ]}
          onChange={(v) => setFailed(v === "failed")}
        />
      </PageHead>
      <Card flush>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <Failed error={q.error} />
        ) : !runs.length ? (
          <Empty>{failed ? "Nothing failed." : "No runs yet."}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table runs">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Kind</th>
                  <th>Workspace</th>
                  <th>Run</th>
                  <th>Agent or engine</th>
                  <th>Model</th>
                  <th className="r">Tokens</th>
                  <th className="r">Cost</th>
                  <th className="r">Took</th>
                  <th className="r">Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const end = r.finished_at ? new Date(r.finished_at).getTime() : null;
                  const start = new Date(r.started_at ?? r.created_at).getTime();
                  const expandable = !!r.error;
                  return (
                    <RunRow key={r.id} run={r} open={open === r.id} onToggle={expandable ? () => setOpen(open === r.id ? null : r.id) : undefined}>
                      <td>
                        <Status status={r.status} />
                      </td>
                      <td>
                        {r.kind}
                        {r.automation && <span className="tag">automation</span>}
                        {r.location === "local" && <span className="tag">local</span>}
                      </td>
                      <td className="mono">{r.workspace ?? "—"}</td>
                      <td className="mono">{r.label}</td>
                      <td>{r.kind === "coding" ? (ENGINE[r.agent ?? ""] ?? r.agent) : (r.agent ?? "—")}</td>
                      <td className="mono dim">{r.model ?? "default"}</td>
                      <td className="r num">{compact(r.input_tokens + r.output_tokens)}</td>
                      <td className="r num">{usd(r.cost_usd)}</td>
                      <td className="r num">{end ? duration((end - start) / 1000) : "—"}</td>
                      <td className="r" title={when(r.created_at)}>
                        {ago(r.created_at, now)}
                      </td>
                    </RunRow>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {q.hasNextPage && (
          <div className="card-foot">
            <button type="button" className="btn btn-secondary" disabled={q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>
              {q.isFetchingNextPage ? "Loading…" : "Older runs"}
            </button>
          </div>
        )}
      </Card>
    </>
  );
}

function RunRow({ run, open, onToggle, children }: { run: Run; open: boolean; onToggle?: () => void; children: ReactNode }) {
  return (
    <>
      <tr className={onToggle ? `click${open ? " open" : ""}` : undefined} onClick={onToggle} aria-expanded={onToggle ? open : undefined}>
        {children}
      </tr>
      {open && run.error && (
        <tr className="detail">
          <td colSpan={10}>
            {run.error_kind && <Pill tone="bad">{run.error_kind}</Pill>}
            <pre>{run.error}</pre>
            <span className="dim mono">{run.id}</span>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Failures

export function FailuresPage() {
  const now = useTick();
  const [days, setDays] = useState(7);
  const q = useQuery({ queryKey: ["failures", days], queryFn: () => call<Failures>(`/ops/observe/failures?days=${days}`), refetchInterval: 60_000 });
  const d = q.data;
  const total = d ? d.messages.reduce((s, g) => s + g.count, 0) : 0;
  return (
    <>
      <PageHead title="Failures" sub="What went wrong, grouped by the error the platform recorded, most frequent first.">
        <Segmented label="Window" value={days} options={DAYS} onChange={setDays} />
      </PageHead>
      {q.isPending ? (
        <Loading />
      ) : q.isError ? (
        <Failed error={q.error} />
      ) : !d!.messages.length ? (
        <Card>
          <Empty>Nothing failed in the last {days} days.</Empty>
        </Card>
      ) : (
        <>
          <Card title="Errors" aside={<span className="muted">{num(total)} failures</span>} flush>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th className="r">Count</th>
                    <th>Kind</th>
                    <th>Error</th>
                    <th className="r">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {d!.messages.map((g) => (
                    <tr key={`${g.kind}:${g.key}`}>
                      <td className="r num strong">{num(g.count)}</td>
                      <td>
                        {g.kind}
                        {g.detail && <span className="tag">{g.detail.replaceAll("_", " ")}</span>}
                      </td>
                      <td className="mono wrap">{g.key}</td>
                      <td className="r">{ago(g.last_at, now)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <div className="grid-2">
            <Card title="Chat runs by kind of error">
              <Breakdown rows={d!.chat_kinds} />
            </Card>
            <Card title="Chat runs by model">
              <Breakdown rows={d!.chat_models} mono />
            </Card>
          </div>
        </>
      )}
    </>
  );
}

function Breakdown({ rows, mono }: { rows: { key: string; count: number }[]; mono?: boolean }) {
  if (!rows.length) return <Empty>None.</Empty>;
  const total = rows.reduce((s, r) => s + r.count, 0);
  return (
    <ul className="breakdown">
      {rows.map((r) => (
        <li key={r.key}>
          <span className={mono ? "mono" : undefined}>{mono ? r.key : words(r.key)}</span>
          <span className="num">{num(r.count)}</span>
          <Meter part={r.count} whole={total} tone="bad" />
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- Coding

export function CodingPage() {
  const [days, setDays] = useState(7);
  const q = useQuery({ queryKey: ["coding", days], queryFn: () => call<CodingRow[]>(`/ops/observe/coding?days=${days}`), refetchInterval: 60_000 });
  const health = useQuery({ queryKey: ["health"], queryFn: () => call<Health>("/ops/observe/health"), refetchInterval: REFRESH });
  const rows = q.data ?? [];
  const sum = (k: keyof CodingRow) => rows.reduce((s, r) => s + (r[k] as number), 0);
  return (
    <>
      <PageHead title="Coding" sub="Kai's turns by engine and by where they ran: how they ended, how long they took, and what they cost.">
        <Segmented label="Window" value={days} options={DAYS} onChange={setDays} />
      </PageHead>
      <div className="tiles">
        <Tile label="Turns" value={num(sum("turns"))} foot={`in ${days} days`} />
        <Tile label="Finished" value={pct(sum("finished"), sum("turns"))} foot="a PR, changes ready, or nothing to change" />
        <Tile label="Failed" value={num(sum("failed"))} foot="or waiting to be recovered" tone={sum("failed") ? "bad" : undefined} />
        <Tile label="Pull requests" value={num(sum("prs"))} />
        <Tile label="Cost" value={usd(sum("cost_usd"))} foot={`${compact(sum("tokens"))} tokens`} />
        <Tile
          label="Sandboxes"
          value={health.data ? `${health.data.sandboxes_warm} warm` : "—"}
          foot={health.data ? `${health.data.sandboxes_asleep} asleep · ${health.data.sandbox}` : undefined}
        />
      </div>
      <Card title="By engine" flush>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <Failed error={q.error} />
        ) : !rows.length ? (
          <Empty>No coding turns in the last {days} days.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Engine</th>
                  <th>Where</th>
                  <th className="r">Turns</th>
                  <th>Finished</th>
                  <th className="r">Failed</th>
                  <th className="r">PRs</th>
                  <th className="r">Median</th>
                  <th className="r">p95</th>
                  <th className="r">Tokens</th>
                  <th className="r">Cost</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.engine}:${r.location}`}>
                    <td className="strong">{ENGINE[r.engine] ?? r.engine}</td>
                    <td>{r.location}</td>
                    <td className="r num">{num(r.turns)}</td>
                    <td>
                      <Meter part={r.finished} whole={r.turns} tone="good" />
                    </td>
                    <td className={`r num${r.failed ? " bad-text" : ""}`}>{num(r.failed)}</td>
                    <td className="r num">{num(r.prs)}</td>
                    <td className="r num">{duration(r.p50_seconds)}</td>
                    <td className="r num">{duration(r.p95_seconds)}</td>
                    <td className="r num">{compact(r.tokens)}</td>
                    <td className="r num">{usd(r.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

const ENGINE: Record<string, string> = { "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode", fx: "fx" };

// ---------------------------------------------------------------- Workspaces

export function WorkspacesPage() {
  const now = useTick();
  const [days, setDays] = useState(7);
  const [find, setFind] = useState("");
  const q = useQuery({
    queryKey: ["workspaces", days],
    queryFn: () => call<WorkspaceRow[]>(`/ops/observe/workspaces?days=${days}&limit=200`),
    refetchInterval: 60_000,
  });
  const term = find.trim().toLowerCase();
  const rows = (q.data ?? []).filter((w) => !term || w.name.toLowerCase().includes(term) || w.slug.includes(term));
  return (
    <>
      <PageHead title="Workspaces" sub="Workspaces by how much they used dotrix: runs, failures, tokens and coding cost.">
        <input
          className="input"
          type="search"
          placeholder="Find a workspace"
          value={find}
          onChange={(e) => setFind(e.target.value)}
          aria-label="Find a workspace"
        />
        <Segmented label="Window" value={days} options={DAYS} onChange={setDays} />
      </PageHead>
      <Card flush>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <Failed error={q.error} />
        ) : !rows.length ? (
          <Empty>{term ? "No workspace matches." : "No workspaces yet."}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Workspace</th>
                  <th className="r">People</th>
                  <th className="r">Projects</th>
                  <th className="r">Chat runs</th>
                  <th className="r">Coding turns</th>
                  <th className="r">Failed</th>
                  <th className="r">Tokens</th>
                  <th className="r">Cost</th>
                  <th className="r">Last run</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((w) => (
                  <tr key={w.id}>
                    <td>
                      <span className="wsn">
                        <b>{w.name}</b>
                        <span className="mono dim">{w.slug}</span>
                        <span className="tag">{w.kind}</span>
                        {w.paused && <Pill tone="warn">agents paused</Pill>}
                      </span>
                    </td>
                    <td className="r num">{num(w.members)}</td>
                    <td className="r num">{num(w.projects)}</td>
                    <td className="r num">{num(w.chat_runs)}</td>
                    <td className="r num">{num(w.coding_runs)}</td>
                    <td className={`r num${w.failed ? " bad-text" : ""}`}>{num(w.failed)}</td>
                    <td className="r num">{compact(w.tokens)}</td>
                    <td className="r num">{usd(w.cost_usd)}</td>
                    <td className="r" title={w.last_run_at ? when(w.last_run_at) : undefined}>
                      {w.last_run_at ? ago(w.last_run_at, now) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- Audit log

const AUDIT_FILTERS = ["", "coding.", "agent_run.", "project.", "github.", "member.", "sandbox_network."];

export function AuditPage() {
  const now = useTick();
  const [action, setAction] = useState("");
  const q = useInfiniteQuery({
    queryKey: ["audit", action],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call<AuditEvent[]>(
        `/ops/audit?limit=100${action ? `&action=${encodeURIComponent(action)}` : ""}${pageParam ? `&before=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    getNextPageParam: (last) => (last.length === 100 ? last[last.length - 1].created_at : null),
  });
  const events = q.data?.pages.flat() ?? [];
  return (
    <>
      <PageHead title="Audit log" sub="What happened, by whom and in which workspace. Details stay in the workspace: they can carry what people wrote.">
        <input
          className="input mono"
          placeholder="Action starts with…"
          value={action}
          onChange={(e) => setAction(e.target.value.trim())}
          aria-label="Filter by action"
        />
      </PageHead>
      <div className="fchips">
        {AUDIT_FILTERS.map((f) => (
          <button key={f} type="button" className={action === f ? "fchip on" : "fchip"} onClick={() => setAction(f)}>
            {f || "Everything"}
          </button>
        ))}
      </div>
      <Card flush>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <Failed error={q.error} />
        ) : !events.length ? (
          <Empty>Nothing recorded.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Workspace</th>
                  <th>By</th>
                  <th className="r">When</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}>
                    <td className="mono strong">{e.action}</td>
                    <td className="mono">{e.workspace ?? "—"}</td>
                    <td>
                      {e.agent ? (
                        <span>agent {e.agent}</span>
                      ) : e.actor_type === "user" ? (
                        <span className="mono dim">person {e.actor_user_id?.slice(0, 8)}</span>
                      ) : (
                        e.actor_type
                      )}
                    </td>
                    <td className="r" title={when(e.created_at)}>
                      {ago(e.created_at, now)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {q.hasNextPage && (
          <div className="card-foot">
            <button type="button" className="btn btn-secondary" disabled={q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>
              {q.isFetchingNextPage ? "Loading…" : "Older events"}
            </button>
          </div>
        )}
      </Card>
    </>
  );
}
