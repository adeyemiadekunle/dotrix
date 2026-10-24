// dotrix's workspace Chat: conversations grouped by project (and
// "All projects"), a new chat with project, agent, and model; replies with what the agent did
// and the changes it proposes; and Kai's coding sessions: inline in the conversation that started them, else listed beside the conversations. Conversations
// and sessions come from the API (TanStack Query); projects, people, and issues still from the store.
// URL: ?thread=ID&project=KEY (or &across=1), ?project=KEY (new chat), ?session=ID (a coding session), ?tab=coding (a new one), ?q=, ?agent=.
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import {
  isActive,
  modelName,
  runTitle,
  useContinueRun,
  useRunSteps,
  useModels,
  useRunStream,
  useSendMessage,
  useStopRun,
  useThread,
  useThreadPlans,
  useWorkspaceThreads,
  wasStopped,
  WORK_MODES,
  APPROVAL_MODES,
  type AgentId,
  type ApprovalMode,
  type Plan,
  type Run,
  type RunStreamState,
  type WorkMode,
} from "@/lib/agent";
import {
  AGENT_NAMES,
  useCodingAvailability,
  useCodingSession,
  useCodingSessions,
  useDecideCoding,
  useFollowUp,
  useStartCoding,
  useRecoverCoding,
  useRevertCoding,
  statusLabel,
  useStopCoding,
  type CodingSession,
} from "@/lib/coding";
import { useCrossConversations, useCrossStream, useCrossThread, useSendCross, useStopCross } from "@/lib/conversations";
import type { Scope } from "@/lib/issues";
import { LimitNotice } from "../components/LimitNotice";
import { approvalModes, defaultApproval } from "../core/can";
import { openPop, openTask } from "../core/actions";
import { Ic } from "../core/icons";
import { go, useRoute } from "../core/nav";
import { MOD, ago, greeting } from "../core/utils";
import { isLive, live } from "../data/live";
import { useLiveAllTasks, useLiveKnowledgeFiles } from "../../lib/workspace-data";
import { D, S, canSee, me, pColor, proj, projByKey, render, task, visibleProjects, who } from "../data/store";
import { Markdown } from "@/components/markdown";
import { RunApprovals } from "../components/RunApprovals";
import { openDocument } from "./Knowledge";
import { Av, PIcon } from "../ui/helpers";
import { moodOf } from "../core/presence";
import { Face } from "../ui/face";
import { CODING_AGENT } from "../data/seed-dotrix";
import { KaiPanel } from "../components/KaiPanel";
import { useAtPicker } from "../components/AtPicker";
import { Splitter, useStoredFlag, useStoredSize } from "../ui/splitter";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const agentName = (h: string) => D().agents.find((a) => a.handle === h)?.name ?? h;
const ms = (at: string | null | undefined) => (at ? new Date(at).getTime() : Date.now());
/** An agent as the store names it: the project manager is "auto". */
const handleOf = (a: string | null | undefined) => (!a || a === "project-manager" || a === "pm" ? "auto" : a);
const wsId = () => live.ws?.id;

const SUGGESTIONS = [
  ["sparkles", "Summarise the project"],
  ["history", "What changed since yesterday?"],
  ["compass", "What should we build next?"],
  ["list-tree", "Turn the requirements into stories"],
];
const ACROSS = [
  ["layers", "Summarise all my projects"],
  ["triangle-alert", "What's at risk this week?"],
];

function open(search: string) {
  go("chat", {}, { search });
}

/* ---------- the list ---------- */

/** A conversation in the list: one in a project, or one across projects. */
interface Row {
  id: string;
  title: string;
  at: number;
  projectId: string | null;
  projectKey: string | null;
  projectKeys: string[];
  waiting: boolean;
}

function useRows(ws: string | undefined) {
  const own = useWorkspaceThreads(ws);
  const cross = useCrossConversations(ws);
  const rows: Row[] = [
    ...(own.data ?? []).map((t) => ({
      id: t.thread_id,
      title: t.title,
      at: ms(t.updated_at),
      projectId: t.project_id,
      projectKey: t.project_key,
      projectKeys: [],
      waiting: t.waiting,
    })),
    ...(cross.data ?? []).map((c) => ({
      id: c.thread_id,
      title: c.title,
      at: ms(c.updated_at),
      projectId: null,
      projectKey: null,
      projectKeys: c.project_keys,
      waiting: false,
    })),
  ];
  return { rows, loaded: own.isFetched && cross.isFetched };
}

const threadSearch = (r: Pick<Row, "id" | "projectKey">) => (r.projectKey ? `thread=${r.id}&project=${r.projectKey}` : `thread=${r.id}&across=1`);

function ThreadRow({ row, on }: { row: Row; on: boolean }) {
  return (
    <button
      className={`sitem ${on ? "on" : ""}`}
      style={{ height: "auto", padding: "6px 8px", alignItems: "flex-start" }}
      onClick={() => open(threadSearch(row))}
    >
      <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
        <span className="trunc" style={{ display: "block", fontWeight: on ? 500 : 400 }}>
          {row.title}
        </span>
        <span className="faint" style={{ fontSize: 11.5 }}>
          {row.projectKeys.length > 0 && `${row.projectKeys.join(", ")} · `}
          {ago(row.at)}
        </span>
      </span>
      {row.waiting && <span className="sdot" style={{ background: "var(--amber)", marginTop: 6 }} aria-label="Waiting for a decision" />}
    </button>
  );
}

function Group({
  title,
  icon,
  color,
  children,
  onNew,
}: {
  title: string;
  icon?: React.ReactNode;
  color?: string;
  children: React.ReactNode;
  onNew: () => void;
}) {
  return (
    <div className="chat-group">
      <div className="row" style={{ padding: "0 8px", height: 26, fontSize: 11.5, color: "var(--text-3)", fontWeight: 500 }}>
        {icon ?? <span className="pdot" style={css({ "--c": color ?? "var(--text-3)", width: 7, height: 7 })} />}
        <span className="grow trunc">{title}</span>
        <button className="ibtn ibtn-xs" onClick={onNew} data-tip="New chat here" aria-label={`New chat in ${title}`}>
          <Ic n="plus" s={13} />
        </button>
      </div>
      {children}
    </div>
  );
}

const STATUS: Record<CodingSession["status"], [string, string]> = {
  awaiting_approval: ["Waiting for approval", "amber"],
  queued: ["Queued", ""],
  running: ["Working", "accent"],
  changes_ready: ["Changes ready", "amber"],
  pr_opened: ["PR opened", "green"],
  no_changes: ["No changes", ""],
  failed: ["Failed", "red"],
  recovery_required: ["Needs recovery", "amber"],
  stopped: ["Stopped", ""],
  rejected: ["Rejected", "red"],
};
const BUSY: CodingSession["status"][] = ["awaiting_approval", "queued", "running", "recovery_required", "changes_ready"];
// Waiting on a person: to start, or (Manual) to push what it changed.
const WAITING: CodingSession["status"][] = ["awaiting_approval", "changes_ready"];

function SessionRow({ cs, on }: { cs: CodingSession; on: boolean }) {
  const [label0, c] = STATUS[cs.status];
  const label = cs.location === "local" && cs.status === "queued" ? "Waiting for your computer" : label0;
  return (
    <div className={`cs-row ${on ? "on" : ""}`}>
      <button
        className={`sitem ${on ? "on" : ""}`}
        style={{ height: "auto", padding: "6px 8px", alignItems: "flex-start", width: "100%" }}
        onClick={() => open(`session=${cs.session_id}`)}
      >
        <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
          <span className="trunc" style={{ display: "block", fontWeight: on ? 500 : 400 }}>
            {cs.pinned && <Ic n="pin" s={11} cls="cs-pin" />}
            <span className="mono faint" style={{ fontSize: 11 }}>
              {cs.issue_key}
            </span>{" "}
            {cs.title ?? cs.issue_title}
          </span>
          <span className="row faint" style={{ fontSize: 11.5, gap: 6 }}>
            {AGENT_NAMES[cs.agent]} · {ago(ms(cs.updated_at))}
            {cs.pr_number && <span>· PR #{cs.pr_number}</span>}
          </span>
        </span>
        <span className={`badge ${c}`} style={{ marginTop: 2 }}>
          {label}
        </span>
      </button>
      <button
        className="ibtn ibtn-xs cs-more"
        onClick={(e) => openPop(e.currentTarget, "session", { id: cs.session_id, session: cs })}
        aria-label={`More for ${cs.issue_key}`}
        aria-haspopup="menu"
      >
        <Ic n="ellipsis" s={14} />
      </button>
    </div>
  );
}

/** Kai's session, inline in the conversation it was started from: its latest turn, and what you can do about it. */
function SessionCard({ cs }: { cs: CodingSession }) {
  const ws = wsId();
  const scope = useMemo(() => (ws ? { workspaceId: ws, projectId: cs.project_id } : undefined), [ws, cs.project_id]);
  const turns = useCodingSession(scope, cs.session_id).data ?? [];
  const latest = turns.at(-1);
  const decide = useDecideCoding(scope, cs.issue_key);
  const stop = useStopCoding(scope, cs.issue_key);
  const recover = useRecoverCoding(scope, cs.issue_key);
  const revert = useRevertCoding(scope, cs.issue_key, defaultApproval());
  const [label0, c] = STATUS[cs.status];
  const label = latest ? statusLabel(latest) : label0;
  const files = latest?.files_changed ?? [];
  const ready = latest?.status === "changes_ready";
  return (
    <div className="change" role="group" aria-label={`Kai on ${cs.issue_key}`} style={{ margin: "4px 0 12px 36px" }}>
      <div className="change-h">
        <Ic n="code" s={14} />
        <b style={{ fontWeight: 500 }}>
          {CODING_AGENT.name} · <span className="mono">{cs.issue_key}</span> {cs.title || cs.issue_title}
        </b>
        <span className="sp" />
        <span className={`badge ${c}`}>{label}</span>
      </div>
      <div className="change-b row muted" style={{ gap: 10, flexWrap: "wrap", fontSize: 12.5 }}>
        <span>
          Turn {cs.turns} · {ago(ms(cs.updated_at))}
        </span>
        {cs.branch && (
          <span className="row" style={{ gap: 4 }}>
            <Ic n="git-branch" s={12} />
            <code>{cs.branch}</code>
          </span>
        )}
        {cs.pr_url && cs.pr_number && (
          <a href={cs.pr_url} target="_blank" rel="noreferrer" style={{ color: "var(--acc)" }}>
            PR #{cs.pr_number}
          </a>
        )}
        {files.length > 0 && (
          <span>
            {files.length} file{files.length === 1 ? "" : "s"} changed
          </span>
        )}
      </div>
      {/* Each turn here: what Kai was asked (the conversation's own messages to it), and what it said back. */}
      {turns.some((t) => t.note || t.summary || t.error) && (
        <div className="change-b" style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 13 }} aria-label="Turns">
          {turns.map((t) => (
            <div key={t.id}>
              {t.note && (
                <div className="muted">
                  <b style={{ fontWeight: 500 }}>Turn {t.turn}:</b> {t.note}
                </div>
              )}
              {t.summary && <Markdown>{t.summary}</Markdown>}
              {t.error && <div style={{ color: "var(--red)" }}>{t.error}</div>}
            </div>
          ))}
        </div>
      )}
      <div className="change-f row" style={{ gap: 6 }}>
        {latest?.can_decide && (
          <>
            <button className="btn btn-sm btn-ghost" disabled={decide.isPending} onClick={() => decide.mutate({ runId: latest.id, decision: "reject" })}>
              {ready ? "Discard changes" : "Reject"}
            </button>
            <button className="btn btn-sm btn-primary" disabled={decide.isPending} onClick={() => decide.mutate({ runId: latest.id, decision: "approve" })}>
              {ready ? "Accept and push" : "Approve"}
            </button>
          </>
        )}
        {latest?.can_revert && (
          <button className="btn btn-sm btn-ghost" disabled={revert.isPending} onClick={() => revert.mutate(latest.id)}>
            Revert this turn
          </button>
        )}
        {latest?.can_stop && (
          <button className="btn btn-sm btn-secondary" disabled={stop.isPending} onClick={() => stop.mutate(latest.id)}>
            Stop
          </button>
        )}
        {latest?.can_recover && (
          <button className="btn btn-sm btn-secondary" disabled={recover.isPending} onClick={() => recover.mutate({ runId: latest.id, action: "check" })}>
            Check and recover
          </button>
        )}
        <span className="sp" />
        <button className="btn btn-sm btn-ghost" onClick={() => open(`session=${cs.session_id}`)}>
          Open the session
          <Ic n="arrow-right" s={12} />
        </button>
      </div>
    </div>
  );
}

/* ---------- a conversation ---------- */

/** One message as Chat draws it: what someone asked, or an agent's reply. */
interface Msg {
  id: string;
  role: "user" | "agent";
  by: string; // member id, or agent handle
  at: number;
  text: string; // Markdown
  activity?: string[];
  tokens?: number;
}

/** Issue keys a reply names, and documents it read: chips that open them. */
function refsOf(
  projectId: string | null,
  text: string,
  activity: string[] = [],
  liveTasks?: { key: string }[],
  liveDocs?: { path: string }[],
): { tasks: string[]; docs: string[] } {
  const tasks = [...new Set(text.match(/\b[A-Z]{2,6}-\d+\b/g) ?? [])].filter((k) => (liveTasks ?? D().tasks).some((t) => t.key === k)).slice(0, 4);
  const docs = projectId
    ? [...new Set(activity.flatMap((a) => a.match(/[\w./-]+\.md\b/g) ?? []))]
        .map(
          (n) =>
            (liveDocs ?? D().knowledge).find(
              (f: { path: string; project?: string }) => (f.project === undefined || f.project === projectId) && (f.path === n || f.path.endsWith(`/${n}`)),
            )?.path,
        )
        .filter((x): x is string => Boolean(x))
        .slice(0, 4)
    : [];
  return { tasks, docs };
}

function Message({ m, projectId, tag, children }: { m: Msg; projectId: string | null; tag?: string; children?: React.ReactNode }) {
  const w = who(m.by);
  const agent = m.role === "agent" ? D().agents.find((a) => a.handle === m.by) : null;
  const [openSteps, setOpenSteps] = useState(false);
  const liveTasks = useLiveAllTasks(live.ws?.id, isLive());
  const liveDocs = useLiveKnowledgeFiles(isLive() && live.ws && projectId ? { workspaceId: live.ws.id, projectId } : undefined, isLive() && m.role === "agent");
  const refs =
    m.role === "agent" ? refsOf(projectId, m.text, m.activity, isLive() ? liveTasks : undefined, isLive() ? liveDocs : undefined) : { tasks: [], docs: [] };
  const p = proj(projectId ?? "");
  const admin = me()?.role === "Owner" || me()?.role === "Admin";
  return (
    <div className={`chat-msg ${m.role}`}>
      {m.role === "agent" ? <Face c={agent?.c ?? "#57544E"} size={26} mood="idle" /> : <Av id={m.by} cls="md" tip={false} />}
      <div className="body">
        <div className="who">
          <b>{m.role === "agent" ? (agent?.name ?? agentName(m.by)) : m.by === D().me ? "You" : w?.name}</b>
          {agent && <span className="role">{agent.role}</span>}
          <time>{ago(m.at)}</time>
          {tag && <span className="badge">{tag}</span>}
          {m.tokens && admin ? <span className="faint">{(m.tokens / 1000).toFixed(1)}k tokens</span> : null}
        </div>
        {m.activity && m.activity.length > 0 && (
          <div className="chat-steps">
            <button className="chat-steps-h" onClick={() => setOpenSteps(!openSteps)} aria-expanded={openSteps}>
              <Ic n={openSteps ? "chevron-down" : "chevron-right"} s={12} />
              Worked through {m.activity.length} step{m.activity.length > 1 ? "s" : ""}
            </button>
            {openSteps && (
              <ul>
                {m.activity.map((a) => (
                  <li key={a}>
                    <Ic n="check" s={11} />
                    {a}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {m.role === "user" ? (
          <div className="said">{m.text}</div>
        ) : (
          m.text && (
            <div className="md">
              <Markdown>{m.text}</Markdown>
            </div>
          )
        )}
        {(refs.tasks.length > 0 || refs.docs.length > 0) && (
          <div className="chat-refs">
            {refs.tasks.map((k) => (
              <button key={k} className="ref" onClick={() => openTask(isLive() ? k : D().tasks.find((t) => t.key === k)!.id)}>
                <Ic n="square-check" s={12} />
                {k}
              </button>
            ))}
            {p &&
              refs.docs.map((d) => (
                <button key={d} className="ref" onClick={() => openDocument(p, d)}>
                  <Ic n="file-text" s={12} />
                  {d}
                </button>
              ))}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

/** A run as two messages: what was asked, and the agent's reply (as it's written, while it works). */
function RunMessages({ run, projectId, scope, stream }: { run: Run; projectId: string | null; scope: Scope | undefined; stream: RunStreamState | null }) {
  const cont = useContinueRun(scope);
  const limited = run.error_kind === "model_limit";
  const interrupted = run.status === "failed" && run.error_kind === "interrupted";
  const failed = run.status === "failed" && !limited;
  const text = stream ? stream.text : (run.reply ?? "");
  const reply: Msg = {
    id: `${run.id}-reply`,
    role: "agent",
    by: handleOf(run.agent),
    at: ms(run.finished_at ?? run.updated_at),
    text: failed ? (wasStopped(run) ? "Stopped." : (run.error ?? "It didn't finish.")) : text,
    activity: stream?.activity ? [stream.activity] : undefined,
    tokens: (run.input_tokens ?? 0) + (run.output_tokens ?? 0) || undefined,
  };
  const shows = !stream || stream.text;
  return (
    <>
      <Message
        m={{ id: run.id, role: "user", by: run.requested_by_id ?? D().me, at: ms(run.created_at), text: run.message || runTitle(run) }}
        projectId={projectId}
        tag={WORK_MODES.find(([v]) => v === run.work_mode)?.[1]}
      />
      {shows && (reply.text || run.approvals?.length || limited) ? (
        <Message m={reply} projectId={projectId}>
          {projectId && <RunApprovals run={run} scope={scope} />}
          {projectId && !stream && <RunSteps scope={scope} runId={run.id} />}
          {limited && projectId && (
            <LimitNotice
              said={run.error ?? undefined}
              resetsAt={run.resumes_at ? ms(run.resumes_at) : null}
              whenReset={run.continue_at_reset}
              onContinue={(whenReset) => cont.mutate({ runId: run.id, whenReset })}
            />
          )}
          {interrupted && projectId && run.requested_by_id === D().me && (
            <div className="row" style={{ gap: 8, marginTop: 8 }}>
              <span className="muted" style={{ fontSize: 12.5 }}>
                It goes on from where it stopped; any change it repeats waits for your approval.
              </span>
              <button className="btn btn-sm btn-secondary" disabled={cont.isPending} onClick={() => cont.mutate({ runId: run.id, whenReset: false })}>
                <Ic n="play" s={12} />
                Continue
              </button>
            </div>
          )}
        </Message>
      ) : null}
    </>
  );
}

/** What the agents did for a reply (kept after the run), folded until asked for. */
function RunSteps({ scope, runId }: { scope: Scope | undefined; runId: string }) {
  const [open, setOpen] = useState(false);
  const steps = useRunSteps(scope, runId, open);
  return (
    <div style={{ marginTop: 6 }}>
      <button className="btn btn-sm btn-ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Ic n={open ? "chevron-down" : "chevron-right"} s={12} />
        Steps
      </button>
      {open && (
        <ol className="muted" style={{ fontSize: 12.5, margin: "4px 0 0 20px" }} aria-label="Steps">
          {steps.data?.length ? steps.data.map((label, i) => <li key={i}>{label}</li>) : <li>{steps.isLoading ? "Loading…" : "No steps kept"}</li>}
        </ol>
      )}
    </div>
  );
}

const MODELS_ICON = "cpu";
const MODE_ICONS: Record<WorkMode, string> = { discuss: "message-circle", plan: "list-checks", build: "hammer", review: "eye" };

/** A version of the conversation's plan; the latest can be built (a Build message naming its version). */
function PlanCard({ plan, latest, busy, onBuild }: { plan: Plan; latest: boolean; busy: boolean; onBuild: () => void }) {
  return (
    <div className="change" role="group" aria-label={`Plan version ${plan.version}`} style={{ margin: "4px 0 12px 36px" }}>
      <div className="change-h">
        <Ic n="list-checks" s={14} />
        <b style={{ fontWeight: 500 }}>{plan.title}</b>
        <span className="badge">Plan v{plan.version}</span>
      </div>
      <div style={{ padding: "8px 12px", fontSize: 13 }}>
        <p style={{ margin: "0 0 8px" }}>{plan.summary}</p>
        {plan.acceptance_criteria.length > 0 && (
          <>
            <div className="faint" style={{ fontSize: 11.5 }}>
              Acceptance criteria
            </div>
            <ul style={{ margin: "2px 0 8px", paddingLeft: 18 }}>
              {plan.acceptance_criteria.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </>
        )}
        <div className="faint" style={{ fontSize: 11.5 }}>
          Tasks
        </div>
        <ol style={{ margin: "2px 0 8px", paddingLeft: 18 }}>
          {plan.tasks.map((t, i) => (
            <li key={i}>
              {t.title}
              {t.depends_on.length > 0 && <span className="faint"> · after {t.depends_on.join(", ")}</span>}
              {t.detail && (
                <div className="muted" style={{ fontSize: 12 }}>
                  {t.detail}
                </div>
              )}
            </li>
          ))}
        </ol>
        {plan.open_questions.length > 0 && (
          <>
            <div className="faint" style={{ fontSize: 11.5 }}>
              Open questions
            </div>
            <ul style={{ margin: "2px 0 0", paddingLeft: 18 }}>
              {plan.open_questions.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          </>
        )}
      </div>
      {latest && (
        <div className="change-f">
          <span className="faint" style={{ fontSize: 12 }}>
            Building asks for your approval before anything changes, and Kai's coding before it starts.
          </span>
          <span className="sp" />
          <button className="btn btn-sm btn-primary" disabled={busy} onClick={onBuild}>
            <Ic n="hammer" s={12} />
            Build this plan
          </button>
        </div>
      )}
    </div>
  );
}

function Pick({
  value,
  onChange,
  options,
  label,
  lead,
}: {
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  label: string;
  lead?: React.ReactNode;
}) {
  return (
    <label className="cpill pick">
      {lead}
      <span className="trunc">{options.find(([v]) => v === value)?.[1] ?? value}</span>
      <Ic n="chevron-down" s={11} />
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}

function Composer({
  placeholder,
  onSend,
  agent,
  setAgent,
  model,
  setModel,
  models,
  autoFocus,
  initial = "",
  context,
  contexts,
  setContext,
  mode,
  setMode,
  approval,
  setApproval,
}: {
  placeholder: string;
  onSend: (text: string, agent: string) => void;
  agent: string;
  setAgent: (a: string) => void;
  model?: string;
  setModel?: (m: string) => void;
  models?: [string, string][];
  autoFocus?: boolean;
  initial?: string;
  context?: string;
  contexts?: [string, string][];
  setContext?: (v: string) => void;
  mode?: WorkMode;
  setMode?: (m: WorkMode) => void;
  approval?: ApprovalMode;
  setApproval?: (m: ApprovalMode) => void;
}) {
  const approvals = APPROVAL_MODES.filter(([v]) => approvalModes().includes(v));
  const [text, setText] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  const a = D().agents.find((x) => x.handle === agent);
  // Typing "@" offers the projects (in a new chat) and the agents.
  const at = useAtPicker({ text, setText, ref, projects: contexts, project: context, onProject: setContext, agent, onAgent: setAgent });
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);
  const send = () => {
    let q = text.trim();
    if (!q || S.ui.offline) return;
    // "@vega …" (or its handle, "@research") picks the agent
    const m = q.match(/^@(\w+)\s+/);
    let pick = agent;
    const named = m && D().agents.find((x) => x.handle === m[1] || x.name.toLowerCase() === m[1]!.toLowerCase());
    if (m && named) {
      pick = named.handle;
      q = q.slice(m[0].length);
      setAgent(pick);
    }
    onSend(q, pick);
    setText("");
  };
  return (
    <div style={{ position: "relative" }}>
      <div className="cbox">
        <textarea
          ref={ref}
          rows={2}
          placeholder={placeholder}
          value={text}
          onChange={(e) => at.onChange(e.target)}
          onKeyDown={(e) => {
            if (at.onKeyDown(e)) return;
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          aria-label="Message"
          aria-expanded={at.open}
        />
        <div className="cbox-row">
          {contexts && setContext && context !== undefined ? (
            <button
              className="cpill pick"
              onClick={at.start}
              aria-label={`Project: ${contexts.find(([v]) => v === context)?.[1]}. Type @ to change it`}
              data-tip="Type @ to pick another project"
            >
              <Ic n={context ? "at-sign" : "layers"} s={12} />
              <span className="trunc">{contexts.find(([v]) => v === context)?.[1]}</span>
            </button>
          ) : (
            context && (
              <span className="cpill" data-tip="What the agents read: the project's documents and board">
                <Ic n="at-sign" s={12} />
                {context}
              </span>
            )
          )}
          {mode && setMode && (
            <span data-tip={WORK_MODES.find(([v]) => v === mode)?.[2]}>
              <Pick
                value={mode}
                onChange={(v) => setMode(v as WorkMode)}
                options={WORK_MODES.map(([v, l]): [string, string] => [v, l])}
                label="Mode"
                lead={<Ic n={MODE_ICONS[mode]} s={12} />}
              />
            </span>
          )}
          {approval && setApproval && approvals.length > 1 && (
            <span data-tip={APPROVAL_MODES.find(([v]) => v === approval)?.[2]}>
              <Pick
                value={approval}
                onChange={(v) => setApproval(v as ApprovalMode)}
                options={approvals.map(([v, l]): [string, string] => [v, l])}
                label="Approvals"
                lead={<Ic n={approval === "manual" ? "shield-check" : "zap"} s={12} />}
              />
            </span>
          )}
          <Pick
            value={agent}
            onChange={setAgent}
            options={D().agents.map((x) => [x.handle, `${x.name} · ${x.role}`])}
            label="Agent"
            lead={a && <Face c={a.c} size={16} mood="idle" />}
          />
          {setModel && models?.length ? (
            <Pick value={model ?? ""} onChange={setModel} options={models ?? []} label="Model" lead={<Ic n={MODELS_ICON} s={12} />} />
          ) : (
            model && (
              <span className="cpill" data-tip="The model is fixed once a conversation starts">
                <Ic n={MODELS_ICON} s={12} />
                {model}
              </span>
            )
          )}
          <span className="sp" />
          <button className="cbox-send" onClick={send} disabled={!text.trim() || S.ui.offline} aria-label="Send">
            <Ic n="arrow-up" s={14} />
          </button>
        </div>
      </div>
      {at.menu}
    </div>
  );
}

function Conversation({ id, projectId, title }: { id: string; projectId: string | null; title: string }) {
  const ws = wsId();
  const p = proj(projectId ?? "");
  const scope = useMemo(() => (ws && projectId ? { workspaceId: ws, projectId } : undefined), [ws, projectId]);
  const own = useThread(scope, projectId ? id : null);
  const cross = useCrossThread(ws, projectId ? null : id);
  const runs = (projectId ? own.data : cross.data) ?? [];
  const last = runs.at(-1);
  const active = Boolean(last && isActive(last));
  const ownStream = useRunStream(scope, last?.id ?? "", Boolean(projectId) && active);
  const crossStream = useCrossStream(ws, last?.id ?? "", !projectId && active);
  const stream = projectId ? ownStream : crossStream;
  const send = useSendMessage(scope);
  const sendCross = useSendCross(ws);
  const stop = useStopRun(scope);
  const stopCross = useStopCross(ws);
  const [picked, setAgent] = useState<string | null>(null);
  const agent = picked ?? handleOf(last?.agent);
  // How you're working: what you picked, else how the conversation was going, else Discuss.
  const [pickedMode, setMode] = useState<WorkMode | null>(null);
  const mode = pickedMode ?? last?.work_mode ?? "discuss";
  // How much goes through without waiting: what you picked, else how the conversation was going (if you still may), else the default.
  const [pickedApproval, setApproval] = useState<ApprovalMode | null>(null);
  const lastApproval = last?.approval_mode && approvalModes().includes(last.approval_mode) ? last.approval_mode : null;
  const approval = pickedApproval ?? lastApproval ?? defaultApproval();
  const plans = useThreadPlans(scope, projectId ? id : null, runs.filter((r) => !isActive(r)).length).data ?? [];
  // Kai's sessions started from this conversation, each after the message that started it.
  const coded = (useCodingSessions(ws, Boolean(projectId)).data ?? []).filter((c) => c.thread_id === id);
  const anchorOf = (c: CodingSession) => runs.filter((r) => ms(r.created_at) <= ms(c.started_at)).at(-1)?.id ?? last?.id;
  // Kai's latest session here: what Build mode's messages go to (its next turn), and what the panel shows.
  const kai = [...coded].filter((c) => c.state !== "closed" && !c.archived).sort((a, b) => ms(b.updated_at) - ms(a.updated_at))[0] ?? null;
  const kaiBusy = Boolean(kai && BUSY.includes(kai.status));
  const kaiScope = useMemo(() => (ws && kai ? { workspaceId: ws, projectId: kai.project_id } : undefined), [ws, kai]);
  const followUp = useFollowUp(kaiScope, kai?.session_id ?? "", kai?.issue_key ?? "", approval);
  const [toKaiPicked, setToKai] = useState<boolean | null>(null);
  const addressed = useRef(false); // an agent was picked or @mentioned for the message being sent
  const toKai = mode === "build" && Boolean(kai) && !kaiBusy && (toKaiPicked ?? true);
  const [panelSet, setPanel] = useStoredFlag("dotrix.chat.kaiPanel");
  const panel = Boolean(kai) && panelSet;
  const latestPlan = plans.at(-1);
  const end = useRef<HTMLDivElement>(null);
  const busy = active && !stream.text;
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [id, runs.length, busy, stream.text]);
  const say = (message: string, a: string, m: WorkMode = mode) =>
    projectId
      ? send.mutate({ message, threadId: id, agent: a as AgentId, workMode: m, approvalMode: approval })
      : sendCross.mutate({ message, thread_id: id, agent: a as AgentId });
  const build = (plan: Plan) => {
    setMode("build");
    say(`Build plan version ${plan.version}: ${plan.title}`, agent, "build");
  };
  const halt = () => last && (projectId ? stop.mutate(last.id) : stopCross.mutate(last.id));
  const about = [...new Set(runs.flatMap((r) => r.project_ids ?? []))].map((pid) => proj(pid)?.name).filter(Boolean);
  // The address named a project (or "across"), so the list wasn't needed to open it; the runs say if it exists.
  if ((projectId ? own.isFetched : cross.isFetched) && runs.length === 0) return <Pending text={MISSING_THREAD} />;
  return (
    <div className="conv">
      <div className="conv-main">
        <div className="row" style={{ height: 46, padding: "0 16px", borderBottom: "1px solid var(--border)", gap: 8, flexShrink: 0 }}>
          <button className="ibtn ibtn-sm" onClick={() => open(p ? `project=${p.key}` : "")} aria-label="Back to conversations">
            <Ic n="arrow-left" s={15} />
          </button>
          <b className="trunc" style={{ fontWeight: 600, fontSize: 13.5 }}>
            {title || (runs[0] ? (runs[0].title ?? runTitle(runs[0])) : "")}
          </b>
          <span className="sp" />
          {p ? (
            <button className="pillbtn" onClick={() => go("project", { id: p.key, tab: "overview" })}>
              <PIcon p={p} s={12} />
              {p.name}
            </button>
          ) : (
            <span className="pillbtn">
              <Ic n="layers" s={13} />
              {about.join(", ") || "All projects"}
            </span>
          )}
          <span className="chat-faces hide-m" aria-label="Agents in this conversation">
            {[...new Set(runs.map((r) => handleOf(r.agent)))].map((h) => {
              const ag = D().agents.find((x) => x.handle === h);
              return ag ? (
                <span key={h} data-tip={`${ag.name} · ${ag.role}`}>
                  <Face c={ag.c} size={20} mood={moodOf(h)} />
                </span>
              ) : null;
            })}
          </span>
          {kai && (
            <button
              className={`ibtn ibtn-sm ${panel ? "on" : ""}`}
              onClick={() => setPanel(!panel)}
              aria-pressed={panel}
              aria-label={`${CODING_AGENT.name}'s work`}
              data-tip={`${CODING_AGENT.name}'s work: changes, files, terminal`}
            >
              <Ic n="panel-right" s={15} />
            </button>
          )}
        </div>
        <div className="chat-scroll">
          <div className="chat-col">
            {runs.map((r) => (
              <div key={r.id}>
                <RunMessages run={r} projectId={projectId} scope={scope} stream={r.id === last?.id && active ? stream : null} />
                {plans
                  .filter((pl) => pl.run_id === r.id)
                  .map((pl) => (
                    <PlanCard key={pl.id} plan={pl} latest={pl.id === latestPlan?.id} busy={active} onBuild={() => build(pl)} />
                  ))}
                {coded
                  .filter((c) => anchorOf(c) === r.id)
                  .map((c) => (
                    <SessionCard key={c.session_id} cs={c} />
                  ))}
              </div>
            ))}
            {active && (
              <div className="chat-msg">
                <Face c={D().agents.find((a) => a.handle === agent)?.c ?? "#E0A92E"} size={26} mood="working" />
                <div className="body">
                  {busy && (
                    <div className="who">
                      <b>{agentName(agent)}</b>
                      <span className="role">{D().agents.find((a) => a.handle === agent)?.role}</span>
                    </div>
                  )}
                  <div className="row muted" style={{ gap: 8, fontSize: 12.5, marginTop: 6 }}>
                    <span className="chat-typing">
                      <i />
                      <i />
                      <i />
                    </span>
                    {stream.activity ?? `${agentName(agent)} is reading the project's documents…`}
                    <span className="sp" />
                    <button className="btn btn-sm btn-ghost" onClick={halt}>
                      Stop
                    </button>
                  </div>
                </div>
              </div>
            )}
            <div ref={end} />
          </div>
        </div>
        <div className="chat-input">
          {mode === "build" && kai && (
            <div className="row" style={{ gap: 8, marginBottom: 6, fontSize: 12 }}>
              <span className="muted">Send to</span>
              <div className="seg" role="radiogroup" aria-label="Send to">
                <button role="radio" aria-checked={toKai} className={toKai ? "on" : ""} disabled={kaiBusy} onClick={() => setToKai(true)}>
                  {CODING_AGENT.name} on {kai.issue_key}
                </button>
                <button role="radio" aria-checked={!toKai} className={!toKai ? "on" : ""} onClick={() => setToKai(false)}>
                  The agents
                </button>
              </div>
              {kaiBusy && <span className="faint">{CODING_AGENT.name} is still on the last turn</span>}
            </div>
          )}
          <Composer
            placeholder={toKai && kai ? `Tell ${CODING_AGENT.name} what to do next on ${kai.issue_key}` : `Ask ${agentName(agent)}, or type @ to pick an agent`}
            agent={agent}
            setAgent={(h) => {
              // Picking an agent, or @mentioning one, addresses the agents, not Kai.
              addressed.current = true;
              setToKai(false);
              setAgent(h);
            }}
            model={modelName(last?.conversation_model) || undefined}
            context={p?.name ?? "All projects"}
            onSend={(q, a) => {
              const named = addressed.current;
              addressed.current = false;
              if (toKai && !named) followUp.mutate(q);
              else say(q, a);
            }}
            mode={projectId ? mode : undefined}
            setMode={projectId ? setMode : undefined}
            approval={projectId ? approval : undefined}
            setApproval={projectId ? setApproval : undefined}
            autoFocus
          />
          {!projectId && (
            <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
              <Ic n="lock" s={11} /> In all projects the agents only read; for a change they'll say which project's chat to ask in.
            </div>
          )}
        </div>
      </div>
      {panel && kai && <KaiPanel cs={kai} onClose={() => setPanel(false)} />}
    </div>
  );
}

function NewChat({ projectKey, across, q, agent0 }: { projectKey: string | null; across: boolean; q: string; agent0: string | null }) {
  const ws = wsId();
  const ps = visibleProjects().filter((p) => canSee(p) && !p.archived);
  const [pid, setPid] = useState<string>(across ? "" : (projByKey(projectKey ?? "")?.id ?? ps[0]?.id ?? ""));
  const [picked, setPicked] = useState<string[]>(ps.slice(0, 3).map((p) => p.id));
  const [agent, setAgent] = useState(agent0 ?? S.ui.chatAgent);
  const models = useModels(ws).data ?? [];
  const [chosen, setModel] = useState<string | null>(null);
  const model = chosen ?? models[0]?.id ?? "";
  const [mode, setMode] = useState<WorkMode>("discuss");
  const [approval, setApproval] = useState<ApprovalMode>(defaultApproval());
  const scope = useMemo(() => (ws && pid ? { workspaceId: ws, projectId: pid } : undefined), [ws, pid]);
  const send = useSendMessage(scope);
  const sendCross = useSendCross(ws);
  const start = (text: string, a: string) => {
    S.ui.chatAgent = a;
    const body = { agent: a as AgentId, model: model || null };
    const started = pid
      ? send
          .mutateAsync({ message: text, threadId: null, ...body, workMode: mode, approvalMode: approval })
          .then((run) => `thread=${run.thread_id}&project=${proj(pid)?.key}`)
      : sendCross.mutateAsync({ message: text, thread_id: null, project_ids: picked, ...body }).then((run) => `thread=${run.thread_id}&across=1`);
    started.then(open, () => {});
  };
  const sugg = pid ? SUGGESTIONS : ACROSS;
  return (
    <div className="chat-scroll" style={{ display: "flex" }}>
      <div className="chat-col" style={{ margin: "auto", paddingTop: 56, paddingBottom: 40 }}>
        <h1 style={{ fontSize: "var(--fs-2xl)", fontWeight: 600, letterSpacing: "-.02em", margin: "0 0 4px", textAlign: "center" }}>
          {greeting()}, {me()?.name.split(" ")[0]}
        </h1>
        <p className="muted" style={{ margin: "0 0 18px", textAlign: "center" }}>
          Ask the agents about a project: they read its documents and board, and propose changes for you to approve.
        </p>
        {!pid && (
          <div className="row" role="group" aria-label="Projects" style={{ gap: 6, marginBottom: 10, flexWrap: "wrap", justifyContent: "center" }}>
            <span className="faint" style={{ fontSize: 12 }}>
              Projects
            </span>
            {ps.map((p) => (
              <label key={p.id} className="badge" style={{ cursor: "pointer", gap: 5 }}>
                <input
                  type="checkbox"
                  checked={picked.includes(p.id)}
                  onChange={() => setPicked(picked.includes(p.id) ? picked.filter((x) => x !== p.id) : [...picked, p.id])}
                />
                {p.name}
              </label>
            ))}
          </div>
        )}
        <Composer
          key={q}
          placeholder="Ask anything, or type @ to pick a project or an agent"
          agent={agent}
          setAgent={setAgent}
          model={model}
          setModel={setModel}
          models={models.map((m): [string, string] => [m.id, m.name])}
          context={pid}
          contexts={[...ps.map((p): [string, string] => [p.id, p.name]), ["", "All projects"]]}
          setContext={setPid}
          mode={pid ? mode : undefined}
          setMode={pid ? setMode : undefined}
          approval={pid ? approval : undefined}
          setApproval={pid ? setApproval : undefined}
          onSend={start}
          autoFocus
          initial={q}
        />
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 14, justifyContent: "center" }}>
          {sugg.map(([i, s]) => (
            <button key={s} className="btn btn-secondary btn-sm" onClick={() => start(s!, agent)} disabled={!pid && !picked.length}>
              <Ic n={i!} s={13} />
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- a new coding session ---------- */

function NewSession({ issue0 }: { issue0: string | null }) {
  // Issues a tool could work on: open ones in the projects you see, and in an organisation only yours.
  const ps = new Set(
    visibleProjects()
      .filter((p) => canSee(p) && !p.archived)
      .map((p) => p.id),
  );
  const personal = D().ws.kind === "personal";
  const liveTasks = useLiveAllTasks(live.ws?.id, isLive());
  const mine =
    (isLive() ? liveTasks : undefined)?.filter(
      (t) => ps.has(t.project) && !t.archived && t.status !== "done" && t.type !== "epic" && (personal || t.assignee === D().me),
    ) ??
    (!isLive()
      ? D().tasks.filter((t) => ps.has(t.project) && !t.archived && t.status !== "done" && t.type !== "epic" && (personal || t.assignee === D().me))
      : []);
  const [tid, setTid] = useState(issue0 ? (isLive() ? issue0 : (D().tasks.find((t) => t.key === issue0)?.id ?? "")) : "");
  const [note, setNote] = useState("");
  const [menu, setMenu] = useState<string | null>(null);
  const [hl, setHl] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);
  const t = task(tid);
  const ws = wsId();
  const pid = t?.project;
  const scope = useMemo(() => (ws && pid ? { workspaceId: ws, projectId: pid } : undefined), [ws, pid]);
  const avail = useCodingAvailability(scope).data;
  // On the platform, or on your own computer when one of yours runs `dotrix runner` for this project.
  const [where, setWhere] = useState<"cloud" | "local" | null>(null);
  const location = where ?? (avail && !avail.available && avail.local_available ? "local" : "cloud");
  const ready = location === "local" ? avail?.local_available : avail?.available;
  const start = useStartCoding(scope, t?.key ?? "", defaultApproval(), location);
  const found = menu === null ? [] : mine.filter((x) => `${x.key} ${x.title}`.toLowerCase().includes(menu.toLowerCase())).slice(0, 8);
  const go_ = () => {
    if (!t) return;
    if (ready === false || start.isPending) return;
    start.mutateAsync(note.trim() || null).then(
      (run) => open(`session=${run.session_id}`),
      () => {},
    );
  };
  const onText = (el: HTMLTextAreaElement) => {
    setNote(el.value);
    const m = el.value.slice(0, el.selectionStart).match(/(?:^|\s)[@/]([\w-]*)$/);
    setMenu(m ? m[1]! : null);
    setHl(0);
  };
  const pick = (id: string) => {
    setTid(id);
    setNote(note.replace(/(^|\s)[@/][\w-]*$/, "$1").replace(/\s+$/, ""));
    setMenu(null);
    ref.current?.focus();
  };
  const ask = () => {
    setNote(note + (note && !note.endsWith(" ") ? " @" : "@"));
    setMenu("");
    setHl(0);
    ref.current?.focus();
  };
  return (
    <div className="chat-scroll" style={{ display: "flex" }}>
      <div className="chat-col" style={{ margin: "auto", paddingTop: 56, paddingBottom: 40 }}>
        <h1 style={{ fontSize: "var(--fs-2xl)", fontWeight: 600, letterSpacing: "-.02em", margin: "0 0 4px", textAlign: "center" }}>Start a coding session</h1>
        <p className="muted" style={{ margin: "0 0 18px", textAlign: "center" }}>
          A coding tool works on an issue on its own branch and opens a pull request. It starts once someone who may approve agent changes says yes.
        </p>
        <div style={{ position: "relative" }}>
          <div className="cbox">
            <textarea
              ref={ref}
              rows={3}
              value={note}
              autoFocus
              placeholder={
                t
                  ? `What should it do? It gets ${t.key}'s description and acceptance criteria either way`
                  : `Type @ or / to pick ${personal ? "an issue" : "one of your issues"}, then say what to do`
              }
              onChange={(e) => onText(e.target)}
              onKeyDown={(e) => {
                if (menu !== null && found.length) {
                  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                    e.preventDefault();
                    setHl((hl + (e.key === "ArrowDown" ? 1 : found.length - 1)) % found.length);
                    return;
                  }
                  if ((e.key === "Enter" && !e.metaKey && !e.ctrlKey) || e.key === "Tab") {
                    e.preventDefault();
                    pick(found[hl]!.id);
                    return;
                  }
                }
                if (e.key === "Escape" && menu !== null) {
                  e.stopPropagation();
                  setMenu(null);
                }
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go_();
              }}
              aria-label="What should it do"
              aria-expanded={menu !== null}
              aria-controls="cs-issues"
            />
            <div className="cbox-row">
              {t ? (
                <span className="cpill" style={{ color: "var(--text)" }}>
                  <Ic n="square-check" s={12} />
                  <span className="trunc">
                    {t.key} {t.title}
                  </span>
                  <button className="ibtn ibtn-xs" style={{ width: 16, height: 16, marginRight: -4 }} onClick={() => setTid("")} aria-label={`Remove ${t.key}`}>
                    <Ic n="x" s={11} />
                  </button>
                </span>
              ) : (
                <button className="cpill pick" onClick={ask} aria-label="Pick an issue">
                  <Ic n="at-sign" s={12} />
                  Issue
                </button>
              )}
              {avail && (avail.local_available || location === "local") && (
                <button
                  className="cpill pick"
                  onClick={() => setWhere(location === "local" ? "cloud" : "local")}
                  aria-label="Where it codes"
                  data-tip={
                    location === "local"
                      ? "In a worktree of your checkout, with the coding tool signed in there; the platform pushes what's accepted"
                      : "In a sandbox on the platform"
                  }
                >
                  <Ic n={location === "local" ? "laptop" : "cloud"} s={12} />
                  {location === "local" ? `On ${avail.local_runner ?? "your computer"}` : "Cloud"}
                </button>
              )}
              {avail && location === "cloud" && (
                <span className="cpill" data-tip={avail.available ? "The coding tool this server runs" : (avail.reason ?? undefined)}>
                  <Ic n="bot" s={12} />
                  {avail.available && avail.agent ? AGENT_NAMES[avail.agent] : "Coding is off"}
                </span>
              )}
              {avail && location === "local" && !avail.local_available && (
                <span className="cpill" data-tip={avail.local_reason ?? undefined}>
                  <Ic n="laptop" s={12} />
                  Not on this computer yet
                </span>
              )}
              <span className="sp" />
              <span className="faint hide-m" style={{ fontSize: 11 }}>
                {MOD}+Enter to start
              </span>
              <button className="btn btn-sm btn-primary" onClick={go_} disabled={!t || ready === false || start.isPending}>
                <Ic n="code" s={13} />
                Start coding
              </button>
            </div>
          </div>
          {menu !== null && (
            <div
              className="pop"
              id="cs-issues"
              role="listbox"
              aria-label="Issues"
              style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, maxWidth: 520 }}
            >
              {found.length ? (
                found.map((x, i) => (
                  <button
                    key={x.id}
                    role="option"
                    aria-selected={i === hl}
                    className={`mi ${i === hl ? "hl" : ""}`}
                    onMouseEnter={() => setHl(i)}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => pick(x.id)}
                  >
                    <span className="faint" style={{ fontSize: 12, width: 64, flexShrink: 0 }}>
                      {x.key}
                    </span>
                    <span className="trunc" style={{ flex: 1 }}>
                      {x.title}
                    </span>
                    <span className="r">{proj(x.project)?.name}</span>
                  </button>
                ))
              ) : (
                <div className="faint" style={{ padding: "8px 10px", fontSize: 12.5 }}>
                  {mine.length ? "No issue matches." : personal ? "No open issues." : "No open issues are assigned to you."}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- a coding session ---------- */

const fileOf = (f: Record<string, unknown>) => String(f.path ?? f.file ?? f.name ?? "");

function Session({ cs }: { cs: CodingSession }) {
  const ws = wsId();
  const scope = useMemo(() => (ws ? { workspaceId: ws, projectId: cs.project_id } : undefined), [ws, cs.project_id]);
  const turns = useCodingSession(scope, cs.session_id).data ?? [];
  const latest = turns.at(-1);
  const decide = useDecideCoding(scope, cs.issue_key);
  const stop = useStopCoding(scope, cs.issue_key);
  const recover = useRecoverCoding(scope, cs.issue_key);
  const revert = useRevertCoding(scope, cs.issue_key, defaultApproval());
  const follow = useFollowUp(scope, cs.session_id, cs.issue_key, defaultApproval());
  const [panel, setPanel] = useStoredFlag("dotrix.chat.kaiPanel");
  const t = isLive() ? { id: cs.issue_key, key: cs.issue_key } : D().tasks.find((x) => x.key === cs.issue_key);
  const p = proj(cs.project_id);
  const tool = AGENT_NAMES[cs.agent];
  const [ask, setAsk] = useState("");
  const [label0, c] = STATUS[cs.status];
  const label = latest ? statusLabel(latest) : label0;
  const busy = BUSY.includes(cs.status) || cs.state === "closed";
  // Its details (tool, project, repo, branches, commit, PR) float over the chat from the ⋮: on hover,
  // or pinned by a click until a click elsewhere or Escape.
  const [info, setInfo] = useState<null | "hover" | "pinned">(null);
  // A screenshot opened large over everything; Escape or a click closes it.
  const [shot, setShot] = useState<{ src: string; name: string } | null>(null);
  useEffect(() => {
    if (!shot) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setShot(null);
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [shot]);
  const infoBtn = useRef<HTMLButtonElement>(null);
  const leave = useRef<number>(0);
  useEffect(() => setInfo(null), [cs.session_id]);
  useEffect(() => {
    if (info !== "pinned") return;
    const away = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest(".cs-info") && !infoBtn.current?.contains(t)) setInfo(null);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setInfo(null);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [info]);
  const hoverIn = () => {
    window.clearTimeout(leave.current);
    setInfo((i) => i ?? "hover");
  };
  const hoverOut = () => {
    leave.current = window.setTimeout(() => setInfo((i) => (i === "hover" ? null : i)), 180);
  };
  const send = () => {
    if (busy || !ask.trim()) return;
    follow.mutate(ask.trim());
    setAsk("");
  };
  const at = infoBtn.current?.getBoundingClientRect();
  const files = latest?.files_changed ?? [];
  const shotSrc = (runId: string, index: number) => `/v1/workspaces/${ws}/projects/${cs.project_id}/coding/runs/${runId}/screenshots/${index}`;
  return (
    <div className="conv">
      <div className="conv-main">
        <div className="row cs-head">
          <button
            className="ibtn ibtn-sm"
            onClick={() => open(cs.thread_id ? `thread=${cs.thread_id}&project=${cs.project_key}` : "")}
            aria-label={cs.thread_id ? "Back to the conversation" : "Back to conversations"}
          >
            <Ic n="arrow-left" s={15} />
          </button>
          <button
            className="mono faint cs-key"
            style={{ fontSize: 12, whiteSpace: "nowrap" }}
            onClick={() => t && openTask(t.id)}
            data-tip="Open the issue"
            aria-label={`Open ${cs.issue_key}`}
          >
            {cs.issue_key}
          </button>
          <b className="trunc" style={{ fontWeight: 600, fontSize: 13.5 }}>
            {cs.title ?? cs.issue_title}
          </b>
          <button
            ref={infoBtn}
            className={`ibtn ibtn-sm ${info ? "on" : ""}`}
            onClick={() => setInfo(info === "pinned" ? null : "pinned")}
            onMouseEnter={hoverIn}
            onMouseLeave={hoverOut}
            aria-label={info ? "Hide the session's details" : "Show the session's details"}
            aria-expanded={!!info}
            aria-haspopup="dialog"
          >
            <Ic n="ellipsis-vertical" s={15} />
          </button>
          <span className={`badge ${c}`}>{label}</span>
          <span className="sp" />
          <button
            className={`ibtn ibtn-sm ${panel ? "on" : ""}`}
            onClick={() => setPanel(!panel)}
            aria-pressed={panel}
            aria-label={`${CODING_AGENT.name}'s work`}
            data-tip={`${CODING_AGENT.name}'s work: changes, files, terminal`}
          >
            <Ic n="panel-right" s={15} />
          </button>
        </div>
        {shot && (
          <div className="cs-lightbox" role="dialog" aria-label={`Screenshot: ${shot.name}`} onClick={() => setShot(null)}>
            <img src={shot.src} alt={`Screenshot: ${shot.name}`} />
            <span>{shot.name}</span>
          </div>
        )}
        {info && at && (
          <div
            className="pop cs-info"
            role="dialog"
            aria-label="The session's details"
            style={{ top: at.bottom + 6, left: Math.max(8, Math.min(at.left - 8, window.innerWidth - 436)) }}
            onMouseEnter={hoverIn}
            onMouseLeave={hoverOut}
          >
            <dl className="kv" style={{ margin: 0 }}>
              <dt>
                <Ic n="bot" s={14} />
                Tool
              </dt>
              <dd>{tool}</dd>
              <dt>
                <Ic n="folder" s={14} />
                Project
              </dt>
              <dd>
                <span className="row" style={{ gap: 6 }}>
                  {p && <span className="pdot" style={css({ "--c": pColor(p) })} />}
                  {cs.project_name}
                </span>
              </dd>
              <dt>
                <Ic n="folder-git-2" s={14} />
                Repository
              </dt>
              <dd>
                {latest?.repo_full_name ? (
                  <a
                    href={`https://github.com/${latest.repo_full_name}`}
                    target="_blank"
                    rel="noreferrer"
                    className="mono"
                    style={{ fontSize: 12, color: "var(--acc)" }}
                  >
                    {latest.repo_full_name}
                  </a>
                ) : (
                  <span className="faint">No repository connected to {cs.project_name}</span>
                )}
              </dd>
              <dt>
                <Ic n="git-branch" s={14} />
                Branch
              </dt>
              <dd className="mono" style={{ fontSize: 12 }}>
                {latest?.base_branch && (
                  <span className="faint">
                    {latest.base_branch}
                    {latest.base_sha ? `@${latest.base_sha.slice(0, 7)}` : ""} →{" "}
                  </span>
                )}
                {cs.branch ?? <span className="faint">a new branch, made when it starts</span>}
              </dd>
              <dt>
                <Ic n="git-commit-horizontal" s={14} />
                Commit
              </dt>
              <dd>
                {latest?.commit_sha ? (
                  <span className="mono faint" style={{ fontSize: 12 }}>
                    {latest.commit_sha.slice(0, 7)}
                  </span>
                ) : (
                  <span className="faint">none yet</span>
                )}
              </dd>
              <dt>
                <Ic n="git-pull-request" s={14} />
                Pull request
              </dt>
              <dd>
                {cs.pr_url && cs.pr_number ? (
                  <a href={cs.pr_url} target="_blank" rel="noreferrer" className="row" style={{ gap: 6, color: "var(--acc)" }}>
                    #{cs.pr_number}
                    {cs.pr_state && (
                      <span className={`badge ${cs.pr_state === "merged" ? "accent" : cs.pr_state === "open" ? "green" : ""}`}>{cs.pr_state}</span>
                    )}
                  </a>
                ) : (
                  <span className="faint">none yet</span>
                )}
              </dd>
            </dl>
          </div>
        )}
        <div className="chat-scroll">
          <div className="chat-col">
            {files.length > 0 && (
              <div className="change" aria-label="Files changed">
                <div className="change-h">
                  <Ic n="files" s={14} />
                  <b style={{ fontWeight: 500 }}>
                    {files.length} file{files.length > 1 ? "s" : ""} changed
                  </b>
                </div>
                <div className="change-b mono" style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
                  {files.map((f, i) => (
                    <span key={i} className="trunc">
                      {fileOf(f)}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {turns.map((turn, i) => (
              <div key={turn.id} style={{ marginBottom: 14 }}>
                <div className="chat-msg user">
                  <Av id={turn.requested_by_id ?? D().me} cls="md" tip={false} />
                  <div className="body">
                    <div className="who">
                      <b>{turn.requested_by_id === D().me ? "You" : (who(turn.requested_by_id ?? "")?.name ?? "Someone")}</b>
                      <time>
                        Turn {i + 1} · {ago(ms(turn.created_at))}
                      </time>
                    </div>
                    <div className="bubble">{turn.note || `Work on ${cs.issue_key}: ${cs.issue_title}`}</div>
                  </div>
                </div>
                {(turn.events.length > 0 || turn.summary || turn.error) && (
                  <div className="chat-msg">
                    <Av id={`agent:${cs.agent}`} cls="md" tip={false} />
                    <div className="body">
                      <div className="who">
                        <b>{tool}</b>
                      </div>
                      <div className="chat-act" style={{ flexDirection: "column", gap: 2 }}>
                        {turn.events
                          .filter((e) => e.kind !== "text" && !e.kind.startsWith("output")) // output: the panel's Terminal
                          .slice(-30)
                          .map((e, j) => (
                            <span key={j}>
                              <Ic n={e.kind === "error" ? "triangle-alert" : "check"} s={11} />
                              {e.text}
                            </span>
                          ))}
                      </div>
                      {turn.summary && (
                        <div className="md">
                          <Markdown>{turn.summary}</Markdown>
                        </div>
                      )}
                      {turn.error && <div className="faint">{turn.error}</div>}
                      {turn.can_revert && !busy && (
                        <button
                          className="btn btn-sm btn-ghost"
                          style={{ alignSelf: "flex-start", marginTop: 4 }}
                          disabled={revert.isPending}
                          onClick={() => revert.mutate(turn.id)}
                        >
                          <Ic n="undo-2" s={12} />
                          Revert this turn
                        </button>
                      )}
                      {(turn.screenshots ?? []).length > 0 && (
                        <div className="cs-shots" aria-label="Screenshots from the browser">
                          {(turn.screenshots ?? []).map((sh) => {
                            const src = shotSrc(turn.id, sh.index);
                            return (
                              <button
                                key={sh.index}
                                className="cs-shot"
                                onClick={() => setShot({ src, name: sh.name })}
                                aria-label={`Open the screenshot ${sh.name}`}
                              >
                                <img src={src} alt={`Screenshot: ${sh.name}`} loading="lazy" />
                                <span className="faint trunc">{sh.name}</span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
            {latest?.status === "awaiting_approval" && (
              <div className="change">
                <div className="change-h">
                  <Ic n="shield-check" s={14} />
                  <b style={{ fontWeight: 500 }}>Waiting for someone who may approve agent changes</b>
                </div>
                <div className="change-f">
                  <span className="faint" style={{ fontSize: 12 }}>
                    It works on its own branch and opens a pull request; a person merges.
                  </span>
                  <span className="sp" />
                  {latest.can_decide && (
                    <>
                      <button
                        className="btn btn-sm btn-secondary"
                        disabled={decide.isPending}
                        onClick={() => decide.mutate({ runId: latest.id, decision: "reject" })}
                      >
                        Reject
                      </button>
                      <button
                        className="btn btn-sm btn-primary"
                        disabled={decide.isPending}
                        onClick={() => decide.mutate({ runId: latest.id, decision: "approve" })}
                      >
                        <Ic n="check" s={13} />
                        Approve
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
            {latest?.status === "changes_ready" && (
              <div className="change" role="group" aria-label="Changes waiting to be accepted">
                <div className="change-h">
                  <Ic n="shield-check" s={14} />
                  <b style={{ fontWeight: 500 }}>Changes ready: nothing is pushed until someone accepts them</b>
                </div>
                {latest.files_changed.length > 0 && (
                  <div className="change-b mono" style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
                    {latest.files_changed.map((f) => (
                      <span key={fileOf(f)} className="row" style={{ gap: 8 }}>
                        <span className="trunc grow">{fileOf(f)}</span>
                        <span style={{ color: "var(--green)" }}>+{String(f.added ?? 0)}</span>
                        <span style={{ color: "var(--red)" }}>-{String(f.removed ?? 0)}</span>
                      </span>
                    ))}
                  </div>
                )}
                <div className="change-f">
                  <span className="faint" style={{ fontSize: 12 }}>
                    Accepted, they're pushed to {latest.branch ? <code>{latest.branch}</code> : "a new branch"} and the pull request is opened or updated.
                  </span>
                  <span className="sp" />
                  {latest.can_stop && !latest.can_decide && (
                    <button className="btn btn-sm btn-secondary" disabled={stop.isPending} onClick={() => stop.mutate(latest.id)}>
                      Discard
                    </button>
                  )}
                  {latest.can_decide && (
                    <>
                      <button
                        className="btn btn-sm btn-secondary"
                        disabled={decide.isPending}
                        onClick={() => decide.mutate({ runId: latest.id, decision: "reject" })}
                      >
                        Discard
                      </button>
                      <button
                        className="btn btn-sm btn-primary"
                        disabled={decide.isPending}
                        onClick={() => decide.mutate({ runId: latest.id, decision: "approve" })}
                      >
                        <Ic n="check" s={13} />
                        Accept and push
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
            {(latest?.status === "running" || latest?.status === "queued") && (
              <div className="row" style={{ gap: 8 }}>
                <span className="chat-typing">
                  <i />
                  <i />
                  <i />
                </span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {latest.status === "queued" ? `${tool} starts soon` : `${tool} is working`}
                </span>
                <span className="sp" />
                {latest.can_stop && (
                  <button className="btn btn-sm btn-secondary" disabled={stop.isPending} onClick={() => stop.mutate(latest.id)}>
                    <Ic n="square" s={12} />
                    Stop
                  </button>
                )}
              </div>
            )}
            {latest?.status === "recovery_required" && (
              <div className="change" role="status">
                <div className="change-h">
                  <Ic n="shield-check" s={14} />
                  <b style={{ fontWeight: 500 }}>This turn was cut off before it finished</b>
                </div>
                <div className="change-f">
                  <span className="faint" style={{ fontSize: 12 }}>
                    {latest.error || "Check GitHub to see what it published before another turn."}
                  </span>
                  <span className="sp" />
                  {latest.can_recover && (
                    <>
                      <button
                        className="btn btn-sm btn-secondary"
                        disabled={recover.isPending}
                        onClick={() => recover.mutate({ runId: latest.id, action: "discard" })}
                      >
                        Discard
                      </button>
                      <button
                        className="btn btn-sm btn-primary"
                        disabled={recover.isPending}
                        onClick={() => recover.mutate({ runId: latest.id, action: "check" })}
                      >
                        <Ic n="refresh-cw" s={12} />
                        Check and recover
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="chat-input">
          <div className="cbox">
            <textarea
              rows={2}
              placeholder={
                cs.state === "closed"
                  ? "This session is closed"
                  : cs.status === "recovery_required"
                    ? "Recover the previous turn before continuing"
                    : busy
                      ? "A turn is waiting or working…"
                      : `Ask ${tool} for a follow-up on the same branch`
              }
              value={ask}
              disabled={busy}
              onChange={(e) => setAsk(e.target.value)}
              aria-label="Follow-up"
              onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && send()}
            />
            <div className="row">
              <span className="faint" style={{ fontSize: 11.5 }}>
                {MOD}+Enter to send · approved like the first turn
              </span>
              <span className="sp" />
              <button className="btn btn-primary btn-sm" disabled={busy || !ask.trim() || follow.isPending} onClick={send}>
                <Ic n="arrow-up" s={13} />
                Send
              </button>
            </div>
          </div>
        </div>
      </div>
      {panel && <KaiPanel cs={cs} onClose={() => setPanel(false)} />}
    </div>
  );
}

const MISSING_THREAD = "This conversation isn't here: it was deleted, or isn't one you can see.";

const Pending = ({ text }: { text: string }) => (
  <div className="chat-scroll" style={{ display: "flex" }}>
    <div className="faint" style={{ margin: "auto", fontSize: 13 }}>
      {text}
    </div>
  </div>
);

export function Chat() {
  const { search } = useRoute();
  const ws = wsId();
  const projectKey = search.get("project");
  const across = search.get("across") === "1";
  const threadId = search.get("thread");
  const sessionId = search.get("session");
  // A new coding session (`?tab=coding`, as "Start coding" links it); otherwise a conversation.
  const newSession = search.get("tab") === "coding" && !sessionId;
  const q = S.ui.chatQ.toLowerCase();
  const ps = visibleProjects().filter(canSee);
  const { rows, loaded } = useRows(ws);
  const sessionsQ = useCodingSessions(ws);
  const allSessions = sessionsQ.data ?? [];
  const row = rows.find((r) => r.id === threadId);
  // A conversation just started isn't listed yet: its address says where it is.
  const thread =
    threadId && (row || across || projectKey)
      ? { id: threadId, projectId: row ? row.projectId : across ? null : (projByKey(projectKey!)?.id ?? null), title: row?.title ?? "" }
      : null;
  const cs = allSessions.find((c) => c.session_id === sessionId) ?? null;
  // Conversations waiting on a decision, Kai's in them included.
  const waitingIn = new Set(allSessions.filter((c) => c.thread_id && WAITING.includes(c.status)).map((c) => c.thread_id));
  const threads = rows
    .filter((r) => !q || r.title.toLowerCase().includes(q))
    .map((r) => (waitingIn.has(r.id) ? { ...r, waiting: true } : r))
    .sort((a, b) => b.at - a.at);
  // Sessions started from a conversation show in it; the others are listed beside the conversations.
  const ownSessions = allSessions.filter((c) => !c.thread_id && (!q || `${c.issue_key} ${c.title ?? c.issue_title}`.toLowerCase().includes(q)));
  const archivedCount = ownSessions.filter((c) => c.archived).length;
  const sessions = ownSessions.filter((c) => c.archived === Boolean(S.ui.showArchivedSessions));
  const hasSel = Boolean(threadId || sessionId || projectKey || across || newSession || search.get("q") || search.get("new"));
  // Column widths, dragged by their edges and kept in this browser.
  const [listW, setListW] = useStoredSize("dotrix.chat.listWidth", 300, 220, 480);
  // The list folds to a rail (like the sidebar) to give the conversation or session the room; not on phones.
  const [listMinSet, setListMin] = useStoredFlag("dotrix.chat.listMin");
  const listMin = listMinSet && !window.matchMedia("(max-width: 900px)").matches;
  // A project's conversations and its own coding sessions, together: pinned sessions first, then the latest.
  const itemsOf = (projectId: string) =>
    [
      ...threads
        .filter((t) => t.projectId === projectId)
        .map((t) => ({ key: t.id, at: t.at, pinned: false, el: <ThreadRow key={t.id} row={t} on={threadId === t.id} /> })),
      ...sessions
        .filter((c) => c.project_id === projectId)
        .map((c) => ({
          key: c.session_id,
          at: ms(c.updated_at),
          pinned: c.pinned,
          el: <SessionRow key={c.session_id} cs={c} on={sessionId === c.session_id} />,
        })),
    ].sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.at - a.at);
  return (
    <div className="page flush">
      <div className={`chat-grid ${hasSel ? "has-sel" : ""}`} style={css({ "--list-w": listMin ? "52px" : `${listW}px` })}>
        <aside className={`chat-side ${listMin ? "min" : ""}`}>
          {listMin ? (
            <div className="chat-rail">
              <button className="ibtn" onClick={() => setListMin(false)} aria-label="Show the list" data-tip="Show the list" data-tip-pos="right">
                <Ic n="panel-left-open" s={16} />
              </button>
              <button className="ibtn" onClick={() => open("new=1")} aria-label="New chat" data-tip="New chat" data-tip-pos="right">
                <Ic n="square-pen" s={15} />
              </button>
              <button className="ibtn" onClick={() => open("tab=coding")} aria-label="New coding session" data-tip="New coding session" data-tip-pos="right">
                <Ic n="code" s={15} />
              </button>
            </div>
          ) : (
            <>
              <Splitter dir="col" className="edge-r" label="Resize the list" onDrag={(d) => setListW((w) => w + d)} />
              <div style={{ padding: "18px 14px 8px" }} className="row">
                <h1 style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600, letterSpacing: "-.015em" }}>Chat</h1>
                <span className="sp" />
                <button className="ibtn ibtn-sm chat-fold" onClick={() => setListMin(true)} aria-label="Hide the list" data-tip="Hide the list">
                  <Ic n="panel-left-close" s={15} />
                </button>
              </div>
              <div style={{ padding: "0 14px 8px" }}>
                <div className="inwrap">
                  <Ic n="search" s={13} />
                  <input
                    className="input search-sm"
                    style={{ width: "100%" }}
                    placeholder="Find a conversation or session"
                    value={S.ui.chatQ}
                    onChange={(e) => ((S.ui.chatQ = e.target.value), render())}
                    aria-label="Find"
                  />
                </div>
                {/* Start something new, under the search: a conversation, or Kai on an issue. */}
                <button className={`sitem chat-new ${!hasSel || search.get("new") ? "on" : ""}`} onClick={() => open("new=1")}>
                  <Ic n="square-pen" s={15} />
                  <span className="trunc">New chat</span>
                </button>
                <button className={`sitem chat-new ${newSession ? "on" : ""}`} onClick={() => open("tab=coding")}>
                  <Ic n="code" s={15} />
                  <span className="trunc">New coding session</span>
                </button>
              </div>
              <nav className="chat-list" aria-label="Conversations">
                {ps.map((p) => {
                  const list = itemsOf(p.id);
                  if (!list.length && q) return null;
                  return (
                    <Group key={p.id} title={p.name} color={pColor(p)} onNew={() => open(`project=${p.key}`)}>
                      {list.length ? (
                        list.map((i) => i.el)
                      ) : (
                        <div className="faint" style={{ fontSize: 12, padding: "2px 8px 4px" }}>
                          No conversations yet
                        </div>
                      )}
                    </Group>
                  );
                })}
                <Group title="Conversations" icon={<Ic n="layers" s={12} />} onNew={() => open("across=1")}>
                  {threads
                    .filter((t) => !t.projectId)
                    .map((t) => (
                      <ThreadRow key={t.id} row={t} on={threadId === t.id} />
                    ))}
                </Group>
                {(archivedCount > 0 || S.ui.showArchivedSessions) && (
                  <button className="linkbtn cs-archived" onClick={() => ((S.ui.showArchivedSessions = !S.ui.showArchivedSessions), render())}>
                    {S.ui.showArchivedSessions ? "Hide archived sessions" : `Show archived sessions (${archivedCount})`}
                  </button>
                )}
              </nav>
            </>
          )}
        </aside>
        <section className="chat-main">
          {sessionId ? (
            cs ? (
              <Session key={cs.session_id} cs={cs} />
            ) : (
              <Pending text={sessionsQ.isFetched ? "This session isn't here: it was deleted, or isn't one you can see." : "Loading the session…"} />
            )
          ) : newSession ? (
            <NewSession key={search.get("issue") ?? ""} issue0={search.get("issue")} />
          ) : threadId ? (
            thread ? (
              <Conversation key={thread.id} id={thread.id} projectId={thread.projectId} title={thread.title} />
            ) : (
              <Pending text={loaded ? MISSING_THREAD : "Loading the conversation…"} />
            )
          ) : (
            <NewChat
              key={`${projectKey}-${across}-${search.get("q")}`}
              projectKey={projectKey}
              across={across}
              q={search.get("q") ?? ""}
              agent0={search.get("agent")}
            />
          )}
        </section>
      </div>
    </div>
  );
}
