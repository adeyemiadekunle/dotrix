// dotrix's workspace Chat: conversations grouped by project (and
// "All projects"), a new chat with project, agent, and model; replies with what the agent did
// and the changes it proposes; and a card for each of Kai's sessions started from a conversation, linking to it in Codes.
// The coding session itself (its turns, the new-session form, the list) is screens/Coding.tsx, built from the pieces exported here.
// Conversations and sessions come from the API (TanStack Query); projects, people, and issues still from the store.
// URL: ?thread=ID&project=KEY (or &across=1), ?project=KEY (new chat), ?q=, ?agent=. Older ?session= and ?tab=coding links open in Codes.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import {
  isActive,
  modelName,
  runTitle,
  useContinueRun,
  useRunSteps,
  useModels,
  useChatRuntimeOptions,
  useRunStream,
  useSendMessage,
  useChatInputs,
  useSubmitChatInput,
  useCancelChatInput,
  useStopRun,
  useThread,
  useThreadPlans,
  useWorkspaceThreads,
  wasStopped,
  WORK_MODES,
  APPROVAL_MODES,
  MODE_ICONS,
  type AgentId,
  type ApprovalMode,
  type ChatRuntime,
  type Plan,
  type Run,
  type RunStreamState,
  type WorkMode,
} from "@/lib/agent";
import {
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
import { desktop, useDesktopRunners } from "../core/desktop";
import { DotsLoader, Ic } from "../core/icons";
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
import { toast } from "../ui/toast";
import { CODING_AGENT } from "../data/seed-dotrix";
import { CODING_VIEWS, CodingPanel, type CodingView } from "../components/SidePanel";
import { useConversationTasks, useReviewRuns, type SpecialistTask } from "@/lib/team";
import { useAtPicker } from "../components/AtPicker";
import { Splitter, useStoredFlag, useStoredSize, useStoredText } from "../ui/splitter";

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
/** Somewhere in Codes: a session (`session=ID`), a new one (`new=1&issue=KEY`), or the list. */
export function openCoding(search: string) {
  go("codes", {}, { search });
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
  return {
    rows,
    loaded: own.isFetched && cross.isFetched,
    failed: own.isError || cross.isError,
    retry: () => {
      void own.refetch();
      void cross.refetch();
    },
  };
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

export function SessionRow({ cs, on }: { cs: CodingSession; on: boolean }) {
  const [label0, c] = STATUS[cs.status];
  const label = cs.location === "local" && cs.status === "queued" ? "Waiting for your computer" : label0;
  return (
    <div className={`cs-row ${on ? "on" : ""}`}>
      <button
        className={`sitem ${on ? "on" : ""}`}
        style={{ height: "auto", padding: "6px 8px", alignItems: "flex-start", width: "100%" }}
        onClick={() => openCoding(`session=${cs.session_id}`)}
      >
        <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
          <span className="trunc" style={{ display: "block", fontWeight: on ? 500 : 400 }}>
            {cs.pinned && <Ic n="pin" s={11} cls="cs-pin" />}
            {cs.thread_id && (
              <span className="faint" aria-label="Started from a conversation" title="Started from a conversation">
                <Ic n="message-square" s={11} />{" "}
              </span>
            )}
            <span className="mono faint" style={{ fontSize: 11 }}>
              {cs.issue_key}
            </span>{" "}
            {cs.title ?? cs.issue_title}
          </span>
          <span className="row faint" style={{ fontSize: 11.5, gap: 6 }}>
            {CODING_AGENT.name} · {ago(ms(cs.updated_at))}
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
        {files.length > 0 && latest && (
          <span className="row" style={{ gap: 6 }}>
            {files.length} file{files.length === 1 ? "" : "s"} changed
            <LineCounts files={files} onClick={() => openCoding(`session=${cs.session_id}&turn=${latest.id}&panel=changes`)} tip="Open the changes in Codes" />
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
        <button className="btn btn-sm btn-ghost" onClick={() => openCoding(`session=${cs.session_id}`)}>
          Open in Codes
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
  const limited = run.chat_runtime !== "fx" && run.error_kind === "model_limit";
  const interrupted = run.chat_runtime !== "fx" && run.status === "failed" && run.error_kind === "interrupted";
  const failed = ["failed", "cancelled", "blocked"].includes(run.status) && !limited;
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
      {run.source !== "coding_outcome" && (
        <Message
          m={{ id: run.id, role: "user", by: run.requested_by_id ?? D().me, at: ms(run.created_at), text: run.message || runTitle(run) }}
          projectId={projectId}
          tag={WORK_MODES.find(([v]) => v === run.work_mode)?.[1]}
        />
      )}
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
function SpecialistTasks({ tasks, scope }: { tasks: SpecialistTask[]; scope: Scope | undefined }) {
  if (!tasks.length) return null;
  return (
    <section className="specialist-tasks" aria-label="Specialist activity">
      {tasks.map((task) => (
        <details className="specialist-task" key={task.id}>
          <summary>
            <b>{agentName(task.agent ?? "auto")}</b>
            <span className="muted">{task.task_key}</span>
            <span className="badge">{task.status.replaceAll("_", " ")}</span>
          </summary>
          <p>{task.task_result?.summary || task.error || task.message}</p>
          {task.task_result?.risks?.map((risk, index) => (
            <p className="muted" key={index}>
              {risk}
            </p>
          ))}
          {task.task_result?.evidence?.length ? (
            <ul>
              {task.task_result.evidence.map((ref, index) => (
                <li className="mono" key={index}>
                  {ref}
                </li>
              ))}
            </ul>
          ) : null}
          {task.status === "awaiting_approval" && <TaskApproval scope={scope} id={task.id} />}
        </details>
      ))}
    </section>
  );
}

function TaskApproval({ scope, id }: { scope: Scope | undefined; id: string }) {
  const run = useReviewRuns(scope, [id])[0];
  return run ? <RunApprovals run={run} scope={scope} /> : null;
}

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
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const name = options.find(([v]) => v === value)?.[1] ?? value;
  return (
    <span
      className="cpill pick"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          setOpen(false);
          btnRef.current?.focus();
        }
      }}
    >
      <button
        ref={btnRef}
        type="button"
        className="pick-open"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${label}: ${name}`}
        onClick={() => setOpen((o) => !o)}
      >
        {lead}
        <span className="trunc">{name}</span>
        <Ic n="chevron-down" s={11} />
      </button>
      {open && (
        <>
          <span className="pick-veil" aria-hidden onClick={() => setOpen(false)} />
          <span className="cmenu" role="listbox" aria-label={label}>
            {options.map(([v, l]) => (
              <button
                key={v}
                type="button"
                role="option"
                aria-selected={v === value}
                className={`mi ${v === value ? "on" : ""}`}
                onClick={() => (onChange(v), setOpen(false))}
              >
                <span className="trunc">{l}</span>
                {v === value && <Ic n="check" s={13} />}
              </button>
            ))}
          </span>
        </>
      )}
    </span>
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
  runtime,
  setRuntime,
  modeOptions = WORK_MODES,
  disabled = false,
}: {
  placeholder: string;
  onSend: (text: string, agent: string) => unknown;
  agent: string;
  setAgent?: (a: string) => void;
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
  runtime?: ChatRuntime;
  setRuntime?: (runtime: ChatRuntime) => void;
  modeOptions?: typeof WORK_MODES;
  disabled?: boolean;
}) {
  const approvals = APPROVAL_MODES.filter(([v]) => approvalModes().includes(v));
  const [text, setText] = useState(initial);
  const [submitting, setSubmitting] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const a = D().agents.find((x) => x.handle === agent);
  // "+" (or typing "@") offers the projects (in a new chat) and the work modes; Nova always answers.
  const at = useAtPicker({ text, setText, ref, projects: contexts, project: context, onProject: setContext, modes: modeOptions, mode, onMode: setMode });
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);
  const send = async () => {
    const q = text.trim();
    if (!q || S.ui.offline || disabled || submitting) return;
    setSubmitting(true);
    try {
      await onSend(q, agent);
      setAgent?.("auto");
      setText("");
    } catch {
      // The mutation reports the error; keep the person's draft for retry.
    } finally {
      setSubmitting(false);
    }
  };
  const modeLabel = WORK_MODES.find(([v]) => v === mode)?.[1] ?? "";
  return (
    <div style={{ position: "relative" }}>
      <div className="cbox">
        <textarea
          ref={ref}
          rows={2}
          placeholder={placeholder}
          value={text}
          disabled={submitting}
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
          {(contexts || (mode && setMode)) && (
            <button
              type="button"
              className="cpill pick"
              onClick={at.start}
              aria-label="Project and mode"
              aria-haspopup="listbox"
              aria-expanded={at.open}
              data-tip="Pick a project or a mode (or type @)"
            >
              <Ic n="plus" s={12} />
            </button>
          )}
          {contexts && setContext && context !== undefined ? (
            <button
              className="cpill pick"
              onClick={at.start}
              aria-label={`Project: ${contexts.find(([v]) => v === context)?.[1]}`}
              aria-haspopup="listbox"
              aria-expanded={at.open}
              data-tip="Pick a project or a mode (or type @)"
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
            <button
              className="cpill pick"
              onClick={at.start}
              aria-label={`Mode: ${modeLabel}`}
              aria-haspopup="listbox"
              aria-expanded={at.open}
              data-tip={WORK_MODES.find(([v]) => v === mode)?.[2]}
            >
              <Ic n={MODE_ICONS[mode]} s={12} />
              <span className="trunc">{modeLabel}</span>
            </button>
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
          {agent !== "auto" && a && setAgent && (
            <button className="cpill" onClick={() => setAgent("auto")} aria-label={`Remove request to involve ${a.name}`}>
              Involve {a.name} <Ic n="x" s={10} />
            </button>
          )}
          {runtime &&
            (setRuntime ? (
              <Pick
                value={runtime}
                onChange={(v) => setRuntime(v as ChatRuntime)}
                options={[
                  ["deepagents", "Standard"],
                  ["fx", "fx preview"],
                ]}
                label="Chat runtime"
              />
            ) : (
              runtime === "fx" && (
                <span className="cpill" data-tip="This conversation uses the read-only fx preview">
                  fx preview
                </span>
              )
            ))}
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
          <button className="cbox-send" onClick={send} disabled={!text.trim() || S.ui.offline || disabled || submitting} aria-label="Send">
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
  const lastUser = runs.filter((run) => run.source === "user").at(-1);
  const fxRun = projectId ? own.data?.filter((run) => run.source === "user").at(-1) : undefined;
  const fxPreview = fxRun?.chat_runtime === "fx";
  const delegated = useConversationTasks(scope, runs);
  const working = runs.find((run) => isActive(run) && run.status !== "waiting_dependency");
  const active = Boolean(working);
  const ownStream = useRunStream(scope, working?.id ?? "", Boolean(projectId) && active);
  const crossStream = useCrossStream(ws, working?.id ?? "", !projectId && active);
  const stream = projectId ? ownStream : crossStream;
  const send = useSendMessage(scope);
  const sendCross = useSendCross(ws);
  const stop = useStopRun(scope);
  const stopCross = useStopCross(ws);
  const chatInputs = useChatInputs(scope, id).data ?? [];
  const submitInput = useSubmitChatInput(scope, id);
  const cancelInput = useCancelChatInput(scope, id);
  const [inputKind, setInputKind] = useState<"queue" | "steer">("queue");
  const awaitingApproval = runs.some((run) => run.status === "awaiting_approval");
  const inputBusy = Boolean(projectId) && (active || awaitingApproval);
  const retryInput = useRef<{ signature: string; client_id: string } | null>(null);
  const agent = "auto";
  // How you're working: what you picked, else how the conversation was going, else Discuss.
  const [pickedMode, setMode] = useState<WorkMode | null>(null);
  const mode = fxPreview ? "discuss" : (pickedMode ?? lastUser?.work_mode ?? "discuss");
  // How much goes through without waiting: what you picked, else how the conversation was going (if you still may), else the default.
  const [pickedApproval, setApproval] = useState<ApprovalMode | null>(null);
  const lastApproval = lastUser?.approval_mode && approvalModes().includes(lastUser.approval_mode) ? lastUser.approval_mode : null;
  const approval = pickedApproval ?? lastApproval ?? defaultApproval();
  const plans = useThreadPlans(scope, projectId ? id : null, runs.filter((r) => !isActive(r)).length).data ?? [];
  // Kai's sessions started from this conversation, each after the message that started it.
  const coded = (useCodingSessions(ws, Boolean(projectId)).data ?? []).filter((c) => c.thread_id === id);
  const anchorOf = (c: CodingSession) => runs.filter((r) => ms(r.created_at) <= ms(c.started_at)).at(-1)?.id ?? last?.id;
  const latestPlan = plans.at(-1);
  const end = useRef<HTMLDivElement>(null);
  const busy = active && !stream.text;
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [id, runs.length, busy, stream.text]);
  const say = (message: string, m: WorkMode = mode) => {
    if (inputBusy) {
      const kind = awaitingApproval ? "queue" : inputKind;
      const retry = retryInput.current;
      const signature = JSON.stringify([id, projectId, message, kind, m, approval]);
      const client_id = retry?.signature === signature ? retry.client_id : crypto.randomUUID();
      retryInput.current = { signature, client_id };
      return submitInput.mutateAsync({ message, kind, client_id, work_mode: m, approval_mode: approval }).then(() => {
        retryInput.current = null;
      });
    }
    return projectId
      ? send.mutateAsync({ message, threadId: id, agent, workMode: m, approvalMode: approval })
      : sendCross.mutateAsync({ message, thread_id: id, agent });
  };
  const build = (plan: Plan) => {
    setMode("build");
    say(`Build plan version ${plan.version}: ${plan.title}`, "build");
  };
  const halt = () => working && (projectId ? stop.mutate(working.id) : stopCross.mutate(working.id));
  const about = [...new Set(runs.flatMap((r) => r.project_ids ?? []))].map((pid) => proj(pid)?.name).filter(Boolean);
  // The address named a project (or "across"), so the list wasn't needed to open it; the runs say if it exists.
  const query = projectId ? own : cross;
  if (query.isLoading) return <Pending text="Loading the conversation…" loading />;
  if (query.isError && !query.data) return <Pending text="The conversation couldn't be loaded." onRetry={() => void query.refetch()} />;
  if (query.isSuccess && runs.length === 0) return <Pending text={MISSING_THREAD} />;
  return (
    <div className="conv">
      <div className="conv-main">
        <div className="row" style={{ height: 46, padding: "0 16px", borderBottom: "1px solid var(--border)", gap: 8, flexShrink: 0 }}>
          <button className="ibtn ibtn-sm" onClick={() => open("")} aria-label="Back to conversations">
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
        </div>
        <div className="chat-scroll">
          <div className="chat-col">
            {runs.map((r) => (
              <div key={r.id}>
                <RunMessages run={r} projectId={projectId} scope={scope} stream={r.id === last?.id && active ? stream : null} />
                <SpecialistTasks tasks={delegated.filter((task) => task.parent_run_id === r.id)} scope={scope} />
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
          {inputBusy && (
            <label className="row muted" style={{ gap: 8, fontSize: 12, marginBottom: 8 }}>
              Send as
              <select
                aria-label="Delivery action"
                value={awaitingApproval ? "queue" : inputKind}
                onChange={(event) => setInputKind(event.target.value as "queue" | "steer")}
              >
                <option value="queue">Queue after this turn</option>
                {!awaitingApproval && <option value="steer">Steer this turn</option>}
              </select>
              <span>
                {inputKind === "steer" && !awaitingApproval ? "Applies at the next safe point; keeps current approvals." : "Waits until this turn completes."}
              </span>
            </label>
          )}
          {chatInputs
            .filter(
              (item) =>
                item.status === "pending" ||
                item.status === "sending" ||
                item.status === "rejected" ||
                (item.status === "accepted" && item.run_id === working?.id),
            )
            .slice(0, 20)
            .reverse()
            .map((item) => (
              <div key={item.id} className="row muted" style={{ gap: 8, fontSize: 12, marginBottom: 6 }}>
                <span>
                  {item.kind === "queue" ? "Queued follow-up" : "Steering"}: {item.message}
                </span>
                <span>{item.status === "accepted" ? "Steering accepted" : item.status}</span>
                {item.error && <span>{item.error}</span>}
                {item.status === "pending" && (
                  <button className="btn btn-sm btn-ghost" disabled={cancelInput.isPending} onClick={() => cancelInput.mutate(item.id)}>
                    Cancel
                  </button>
                )}
              </div>
            ))}
          <Composer
            placeholder="Ask Nova, or type @ to pick a mode"
            agent={agent}
            model={modelName(last?.conversation_model) || undefined}
            context={p?.name ?? "All projects"}
            onSend={(q) => say(q)}
            mode={projectId ? mode : undefined}
            setMode={projectId ? setMode : undefined}
            modeOptions={fxPreview ? WORK_MODES.filter(([value]) => value === "discuss") : WORK_MODES}
            runtime={fxPreview ? "fx" : undefined}
            approval={projectId ? approval : undefined}
            setApproval={projectId ? setApproval : undefined}
            autoFocus
          />
          {fxPreview && (
            <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
              {fxRun?.orchestration
                ? "The fx preview can ask built-in specialists for read-only work. It cannot change data or start coding yet."
                : "The fx preview reads project knowledge. It cannot delegate, change data, or start coding yet."}
            </div>
          )}
          {!projectId && (
            <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
              <Ic n="lock" s={11} /> In all projects the agents only read; for a change they'll say which project's chat to ask in.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NewChat({ projectKey, across, q, agent0 }: { projectKey: string | null; across: boolean; q: string; agent0: string | null }) {
  const ws = wsId();
  const ps = visibleProjects().filter((p) => canSee(p) && !p.archived);
  const [pid, setPid] = useState<string>(across ? "" : (projByKey(projectKey ?? "")?.id ?? ps[0]?.id ?? ""));
  const [picked, setPicked] = useState<string[]>(ps.slice(0, 3).map((p) => p.id));
  const [agent, setAgent] = useState(agent0 ?? "auto");
  const models = useModels(ws).data ?? [];
  const [chosen, setModel] = useState<string | null>(null);
  const [mode, setMode] = useState<WorkMode>("discuss");
  const [runtime, setRuntime] = useState<ChatRuntime>("deepagents");
  const [approval, setApproval] = useState<ApprovalMode>(defaultApproval());
  const scope = useMemo(() => (ws && pid ? { workspaceId: ws, projectId: pid } : undefined), [ws, pid]);
  const runtimeOptions = useChatRuntimeOptions(scope).data;
  const availableModels = runtime === "fx" ? models.filter((m) => m.source === "personal" && runtimeOptions?.fx_providers.includes(m.provider)) : models;
  const model = availableModels.some((m) => m.id === chosen) ? chosen! : (availableModels[0]?.id ?? "");
  const unavailable = runtime === "fx" && !model;
  const send = useSendMessage(scope);
  const sendCross = useSendCross(ws);
  const start = (text: string, a: string) => {
    const body = { agent: a as AgentId, model: model || null };
    const started = pid
      ? send
          .mutateAsync({ message: text, threadId: null, ...body, workMode: mode, approvalMode: approval, chatRuntime: runtime })
          .then((run) => `thread=${run.thread_id}&project=${proj(pid)?.key}`)
      : sendCross.mutateAsync({ message: text, thread_id: null, project_ids: picked, ...body }).then((run) => `thread=${run.thread_id}&across=1`);
    started.then(open, () => {});
  };
  const sugg = pid ? SUGGESTIONS : ACROSS;
  return (
    <div className="conv">
      <button className="ibtn chat-new-back" onClick={() => open("")} aria-label="Back to conversations">
        <Ic n="arrow-left" s={16} />
      </button>
      <div className="chat-scroll" style={{ display: "flex" }}>
        <div className="chat-col" style={{ margin: "auto", paddingTop: 56, paddingBottom: 40 }}>
          <h2 style={{ fontSize: "var(--fs-2xl)", fontWeight: 600, letterSpacing: "-.02em", margin: "0 0 4px", textAlign: "center" }}>
            {greeting()}, {me()?.name.split(" ")[0]}
          </h2>
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
            placeholder="Ask anything, or type @ to pick a project or a mode"
            agent={agent}
            setAgent={setAgent}
            model={model}
            setModel={setModel}
            models={availableModels.map((m): [string, string] => [m.id, m.name])}
            context={pid}
            contexts={[...ps.map((p): [string, string] => [p.id, p.name]), ["", "All projects"]]}
            setContext={(value) => {
              setPid(value);
              if (!value) setRuntime("deepagents");
            }}
            mode={pid ? mode : undefined}
            setMode={pid ? setMode : undefined}
            modeOptions={runtime === "fx" ? WORK_MODES.filter(([value]) => value === "discuss") : WORK_MODES}
            runtime={pid && runtimeOptions?.fx_available ? runtime : undefined}
            setRuntime={
              pid && runtimeOptions?.fx_available
                ? (value) => {
                    setRuntime(value);
                    if (value === "fx") {
                      setMode("discuss");
                      setAgent("auto");
                    }
                  }
                : undefined
            }
            disabled={unavailable}
            approval={pid ? approval : undefined}
            setApproval={pid ? setApproval : undefined}
            onSend={start}
            autoFocus
            initial={q}
          />
          {runtime === "fx" && (
            <div className="faint" style={{ fontSize: 11.5, marginTop: 6, textAlign: "center" }}>
              {unavailable
                ? "Connect a compatible personal model in settings to use the fx preview."
                : runtimeOptions?.fx_delegation_available
                  ? "The fx preview can ask built-in specialists for read-only work. It cannot change data or start coding yet."
                  : "The fx preview reads project knowledge. It cannot delegate, change data, or start coding yet."}
            </div>
          )}
          <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 14, justifyContent: "center" }}>
            {sugg.map(([i, s]) => (
              <button key={s} className="btn btn-secondary btn-sm" onClick={() => start(s!, agent)} disabled={unavailable || (!pid && !picked.length)}>
                <Ic n={i!} s={13} />
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- a new coding session ---------- */

export function NewSession({ issue0 }: { issue0: string | null }) {
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
  const [menuBtn, setMenuBtn] = useState(false);
  const [hl, setHl] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);
  const t = mine.find((issue) => issue.id === tid) ?? task(tid);
  const ws = wsId();
  const pid = t?.project;
  const scope = useMemo(() => (ws && pid ? { workspaceId: ws, projectId: pid } : undefined), [ws, pid]);
  const avail = useCodingAvailability(scope).data;
  const [chosenModel, setChosenModel] = useState<string | null>(null);
  // On the platform, or on your own computer when one of yours runs `dotrix runner` for this project.
  const [where, setWhere] = useState<"cloud" | "local" | null>(null);
  const location = where ?? (avail && !avail.available && avail.local_available ? "local" : "cloud");
  // Kai codes on the model you pick here, your default model to start with. The engine that runs it follows from
  // the model (your preferred engine in Account → Your models, else the model's provider's own); on your own
  // computer, the tool signed in there decides.
  const models = location === "cloud" ? (avail?.models ?? []) : [];
  const model = location === "cloud" ? ((chosenModel && models.includes(chosenModel) ? chosenModel : avail?.default_model) ?? models[0] ?? null) : null;
  const ready = location === "local" ? avail?.local_available && (avail.local_tools ?? []).length > 0 : avail?.available && !!model;
  // In the desktop app, a folder of this computer's picked here starts its runner (core/desktop.ts).
  const here = desktop();
  const runners = useDesktopRunners();
  const slug = live.slug;
  const pkey = pid ? proj(pid)?.key : undefined;
  const hereRunner = runners.find((r) => r.workspace === slug && r.projectKey === pkey);
  const [adding, setAdding] = useState(false);
  const qc = useQueryClient();
  const hereState = runners.map((r) => `${r.projectKey}:${r.state}`).join();
  useEffect(() => {
    if (pid) void qc.invalidateQueries({ queryKey: ["coding", pid] }); // a runner registered or stopped
  }, [hereState, pid, qc]);
  const codeHere = () => {
    if (!here || !slug || !pkey) return;
    setAdding(true);
    here.runners
      .add(slug, pkey)
      .catch((e: unknown) => toast(e instanceof Error ? e.message : "This computer's runner didn't start", { kind: "err" }))
      .finally(() => setAdding(false));
  };
  const start = useStartCoding(scope, t?.key ?? "", defaultApproval(), location, null, model);
  // The issue list opens two ways: typing "@" or "/" (menu is the query) or the Issue button (menuBtn); the button never touches the note.
  const menuOpen = menu !== null || menuBtn;
  const found = !menuOpen ? [] : mine.filter((x) => `${x.key} ${x.title}`.toLowerCase().includes((menu ?? "").toLowerCase())).slice(0, 8);
  const go_ = () => {
    if (!t) return;
    if (!ready || start.isPending) return;
    start.mutateAsync(note.trim() || null).then(
      (run) => openCoding(`session=${run.session_id}`),
      () => {},
    );
  };
  const onText = (el: HTMLTextAreaElement) => {
    setNote(el.value);
    const m = el.value.slice(0, el.selectionStart).match(/(?:^|\s)[@/]([\w-]*)$/);
    setMenu(m ? m[1]! : null);
    setMenuBtn(false);
    setHl(0);
  };
  const pick = (id: string) => {
    setTid(id);
    if (menu !== null) setNote(note.replace(/(^|\s)[@/][\w-]*$/, "$1").replace(/\s+$/, ""));
    setMenu(null);
    setMenuBtn(false);
    ref.current?.focus();
  };
  const ask = () => {
    if (menuOpen) {
      setMenu(null);
      setMenuBtn(false);
      return;
    }
    setMenuBtn(true);
    setHl(0);
    ref.current?.focus();
  };
  return (
    <div className="chat-scroll" style={{ display: "flex" }}>
      <div className="chat-col" style={{ margin: "auto", paddingTop: 56, paddingBottom: 40 }}>
        <h2 style={{ fontSize: "var(--fs-2xl)", fontWeight: 600, letterSpacing: "-.02em", margin: "0 0 4px", textAlign: "center" }}>Start a session</h2>
        <p className="muted" style={{ margin: "0 0 18px", textAlign: "center" }}>
          Kai works on an issue on its own branch and opens a pull request. It starts once someone who may approve agent changes says yes.
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
                if (menuOpen && found.length) {
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
                if (e.key === "Escape" && menuOpen) {
                  e.stopPropagation();
                  setMenu(null);
                  setMenuBtn(false);
                }
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go_();
              }}
              aria-label="What should it do"
              aria-expanded={menuOpen}
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
                <button className="cpill pick" onClick={ask} aria-label="Pick an issue" aria-haspopup="listbox" aria-expanded={menuOpen}>
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
              {model && (
                <Pick value={model} label="Model" lead={<Ic n="sparkles" s={12} />} onChange={setChosenModel} options={models.map((m) => [m, modelName(m)])} />
              )}
              {avail && location === "cloud" && !avail.available && (
                <span className="cpill" data-tip={avail.reason ?? undefined}>
                  Coding is off
                </span>
              )}
              {avail && location === "local" && !avail.local_available && !here && (
                <span className="cpill" data-tip={avail.local_reason ?? undefined}>
                  <Ic n="laptop" s={12} />
                  Not on this computer yet
                </span>
              )}
              {avail && location === "local" && !avail.local_available && here && (
                <button
                  className="cpill pick"
                  onClick={codeHere}
                  disabled={!slug || !pkey || adding}
                  aria-label="Local"
                  data-tip={
                    hereRunner?.state === "failed"
                      ? (hereRunner.message ?? "This computer's runner stopped")
                      : "Choose your checkout of the project's repository: this app codes its turns there, in a worktree"
                  }
                >
                  <Ic n="folder-plus" s={12} />
                  {adding || hereRunner?.state === "starting" ? "Starting…" : hereRunner?.state === "failed" ? "Runner stopped: choose again" : "Local"}
                </button>
              )}
              <span className="sp" />
              <span className="faint hide-m" style={{ fontSize: 11 }}>
                {MOD}+Enter to start
              </span>
              <button className="btn btn-sm btn-primary" onClick={go_} disabled={!t || !ready || start.isPending}>
                <Ic n="code" s={13} />
                Start coding
              </button>
            </div>
          </div>
          {menuOpen && (
            <>
              <span
                className="pick-veil"
                aria-hidden
                onClick={() => {
                  setMenu(null);
                  setMenuBtn(false);
                }}
              />
              <div
                className="pop"
                id="cs-issues"
                role="listbox"
                aria-label="Issues"
                style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, maxWidth: 520, zIndex: 80 }}
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
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- a coding session ---------- */

const fileOf = (f: Record<string, unknown>) => String(f.path ?? f.file ?? f.name ?? "");
/** A turn's lines added and removed, from its changed files. */
const lineCounts = (files: Record<string, unknown>[]) =>
  files.reduce<[number, number]>((sum, f) => [sum[0] + (Number(f.added) || 0), sum[1] + (Number(f.removed) || 0)], [0, 0]);
/** Lines added and removed, as Claude Code shows them; a button when it opens the changes. */
function LineCounts({ files, onClick, tip }: { files: Record<string, unknown>[]; onClick?: () => void; tip?: string }) {
  const [added, removed] = lineCounts(files);
  const body = (
    <>
      <span style={{ color: "var(--green)" }}>+{added}</span> <span style={{ color: "var(--red)" }}>−{removed}</span>
    </>
  );
  return onClick ? (
    <button className="pillbtn mono line-counts" onClick={onClick} data-tip={tip} aria-label={`${added} lines added, ${removed} removed. ${tip ?? ""}`.trim()}>
      {body}
    </button>
  ) : (
    <span className="mono line-counts">{body}</span>
  );
}
/** Text with the paths it names (from `paths`) as buttons that open them. */
function PathLinks({ text, paths, onPath }: { text: string; paths: string[]; onPath: (path: string) => void }) {
  const found = paths.filter((path) => path && text.includes(path)).sort((a, b) => b.length - a.length);
  if (!found.length) return <>{text}</>;
  const pattern = new RegExp(`(${found.map((path) => path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`);
  return (
    <>
      {text.split(pattern).map((part, i) =>
        found.includes(part) ? (
          <button key={i} className="path-link mono" onClick={() => onPath(part)} data-tip="Open in Files">
            {part}
          </button>
        ) : (
          part
        ),
      )}
    </>
  );
}

export function Session({ cs }: { cs: CodingSession }) {
  const ws = wsId();
  const scope = useMemo(() => (ws ? { workspaceId: ws, projectId: cs.project_id } : undefined), [ws, cs.project_id]);
  const turns = useCodingSession(scope, cs.session_id).data ?? [];
  const latest = turns.at(-1);
  const decide = useDecideCoding(scope, cs.issue_key);
  const stop = useStopCoding(scope, cs.issue_key);
  const recover = useRecoverCoding(scope, cs.issue_key);
  const revert = useRevertCoding(scope, cs.issue_key, defaultApproval());
  const follow = useFollowUp(scope, cs.session_id, cs.issue_key, defaultApproval());
  const search = useRoute().search;
  // Which view the side panel shows: the address's (`panel=`, or Files for a `file=` link), else the last one
  // opened in this browser ("" when it was closed). Older links say `panel=coding`: Changes.
  const [lastView, setLastView] = useStoredText("dotrix.coding.panelView", "");
  const asked = search.get("panel") === "coding" ? "changes" : search.get("panel");
  const view = (CODING_VIEWS.find((v) => v.id === (asked ?? (search.has("file") ? "files" : lastView)))?.id ?? null) as CodingView | null;
  const showView = (next: CodingView | null, extra: Record<string, string> = {}) => {
    const query = new URLSearchParams(search);
    // Switching views keeps the file and turn a link opened; closing, or opening something new, lets them go.
    for (const key of !next || Object.keys(extra).length ? ["panel", "file", "line", "turn"] : ["panel"]) query.delete(key);
    if (next) query.set("panel", next);
    for (const [key, value] of Object.entries(extra)) query.set(key, value);
    go("codes", {}, { search: query.toString(), replace: true });
    setLastView(next ?? "");
  };
  const closePanel = () => showView(null);
  // The address always says when the panel is open (the list beside the session folds for it: screens/Coding.tsx).
  useEffect(() => {
    if (view && !search.has("panel")) showView(view);
  });
  const toggleView = (next: CodingView) => showView(view === next ? null : next);
  /** A file the session changed, opened in Files (in the latest turn that changed it, or the latest). */
  const openPath = (path: string, turnId?: string) => {
    const owner = turnId ?? [...turns].reverse().find((t) => t.files_changed.some((f) => fileOf(f) === path))?.id ?? latest?.id;
    showView("files", { file: path, ...(owner ? { turn: owner } : {}) });
  };
  // Claude Code's shortcuts: ⌘/Ctrl+\ closes the panel, ⌘/Ctrl+Shift+D the changes, Ctrl+` the terminal.
  const keys = useRef({ view, toggleView, closePanel });
  keys.current = { view, toggleView, closePanel };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === "\\" && keys.current.view) {
        e.preventDefault();
        keys.current.closePanel();
      } else if (mod && e.shiftKey && e.key.toLowerCase() === "d") {
        e.preventDefault();
        keys.current.toggleView("changes");
      } else if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        keys.current.toggleView("terminal");
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  const t = isLive() ? { id: cs.issue_key, key: cs.issue_key } : D().tasks.find((x) => x.key === cs.issue_key);
  const p = proj(cs.project_id);
  // People see Kai; the engine underneath (cs.agent) stays on the run and in the logs.
  const kai = CODING_AGENT.name;
  const [ask, setAsk] = useState("");
  const [label0, c] = STATUS[cs.status];
  const label = latest ? statusLabel(latest) : label0;
  const busy = BUSY.includes(cs.status) || cs.state === "closed";
  // Its details (project, repo, branches, commit, PR) float over the chat from the ⋮: on hover,
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
  const changedTurn = [...turns].reverse().find((t) => t.files_changed.length > 0);
  const shotSrc = (runId: string, index: number) => `/v1/workspaces/${ws}/projects/${cs.project_id}/coding/runs/${runId}/screenshots/${index}`;
  return (
    <div className="conv">
      <div className="conv-main">
        <div className="row cs-head">
          <button className="ibtn ibtn-sm" onClick={() => openCoding("")} aria-label="Back to sessions">
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
          {cs.thread_id && (
            // Started from a conversation: its outcome goes back there; the link opens it (it stays private to whoever started it).
            <button
              className="pillbtn"
              onClick={() => open(`thread=${cs.thread_id}&project=${cs.project_key}`)}
              data-tip="The conversation this session came from"
            >
              <Ic n="message-square" s={12} />
              From a conversation
            </button>
          )}
          <span className="sp" />
          {changedTurn && (
            <LineCounts
              files={changedTurn.files_changed}
              onClick={() => showView("changes", { turn: changedTurn.id })}
              tip={`Changes in turn ${changedTurn.turn}`}
            />
          )}
          {/* Each view opens the side panel on it, as Claude Code's title bar opens its panes (icons, named on hover); the open one closes it. */}
          <div className="cs-views" role="group" aria-label="Side panel">
            {CODING_VIEWS.map((v) => (
              <button
                key={v.id}
                className={`cs-view ${view === v.id ? "on" : ""}`}
                onClick={() => toggleView(v.id)}
                aria-pressed={view === v.id}
                aria-label={v.label}
                data-tip={v.id === "changes" ? `${v.label}  ${MOD}⇧D` : v.id === "terminal" ? `${v.label}  Ctrl \`` : v.label}
              >
                <Ic n={v.icon} s={15} />
              </button>
            ))}
          </div>
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
                  <span className="sp" />
                  <LineCounts files={files} onClick={() => latest && showView("changes", { turn: latest.id })} tip="Open the changes" />
                </div>
                <div className="change-b mono" style={{ fontSize: 12, display: "flex", flexDirection: "column", gap: 2 }}>
                  {files.map((f, i) => (
                    <button key={i} className="path-link trunc" onClick={() => openPath(fileOf(f), latest?.id)} data-tip="Open in Files">
                      {fileOf(f)}
                    </button>
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
                    <Av id={CODING_AGENT.id} cls="md" tip={false} />
                    <div className="body">
                      <div className="who">
                        <b>{kai}</b>
                      </div>
                      <div className="chat-act" style={{ flexDirection: "column", gap: 2 }}>
                        {turn.events
                          .filter((e) => e.kind !== "text" && !e.kind.startsWith("output")) // output: the panel's Terminal
                          .slice(-30)
                          .map((e, j) => (
                            <span key={j}>
                              <Ic n={e.kind === "error" ? "triangle-alert" : "check"} s={11} />
                              <PathLinks text={e.text} paths={turn.files_changed.map(fileOf)} onPath={(path) => openPath(path, turn.id)} />
                            </span>
                          ))}
                      </div>
                      {turn.summary && (
                        <div className="md">
                          <Markdown
                            onCode={(code) =>
                              turn.files_changed.some((f) => fileOf(f) === code.replace(/:\d+$/, ""))
                                ? () => openPath(code.replace(/:\d+$/, ""), turn.id)
                                : undefined
                            }
                          >
                            {turn.summary}
                          </Markdown>
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
                        <button className="path-link trunc grow" onClick={() => openPath(fileOf(f), latest.id)} data-tip="Open in Files">
                          {fileOf(f)}
                        </button>
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
                  {latest.status === "queued" ? `${kai} starts soon` : `${kai} is working`}
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
                      : `Ask ${kai} for a follow-up on the same branch`
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
      {view && (
        <CodingPanel scope={scope} cs={cs} view={view} onView={showView} onClose={closePanel} onAskFix={setAsk} fixLabel={`Ask ${CODING_AGENT.name} to fix`} />
      )}
    </div>
  );
}

const MISSING_THREAD = "This conversation isn't here: it was deleted, or isn't one you can see.";

export const Pending = ({
  text,
  loading = false,
  onRetry,
  inbox = false,
  back = ["Back to conversations", () => open("")],
}: {
  text: string;
  loading?: boolean;
  onRetry?: () => void;
  inbox?: boolean;
  back?: [string, () => void];
}) => (
  <div className="chat-scroll" style={{ display: "flex" }}>
    <div className="chat-pending" role={loading ? "status" : undefined}>
      {loading && <DotsLoader px={44} />}
      <span>{text}</span>
      {onRetry && (
        <button className="btn btn-secondary btn-sm" onClick={onRetry}>
          Try again
        </button>
      )}
      {inbox && (
        <button className="btn btn-secondary btn-sm" onClick={() => go("inbox", {}, { search: "tab=needs" })}>
          Open Inbox
        </button>
      )}
      {!loading && (
        <button className="btn btn-ghost btn-sm" onClick={back[1]}>
          {back[0]}
        </button>
      )}
    </div>
  </div>
);

/** Older links to a coding session or a new one (`?session=`, `?tab=coding`) open in Codes. */
function ToCoding({ search }: { search: URLSearchParams }) {
  const query = new URLSearchParams(search);
  if (query.get("tab") === "coding") {
    query.delete("tab");
    if (!query.has("session")) query.set("new", "1");
  }
  const to = query.toString();
  useEffect(() => go("codes", {}, { search: to, replace: true }), [to]);
  return null;
}

export function Chat() {
  const { search } = useRoute();
  if (search.has("session") || search.get("tab") === "coding") return <ToCoding search={search} />;
  return <Conversations search={search} />;
}

function Conversations({ search }: { search: URLSearchParams }) {
  const ws = wsId();
  const projectKey = search.get("project");
  const across = search.get("across") === "1";
  const threadId = search.get("thread");
  const q = S.ui.chatQ.toLowerCase();
  const ps = visibleProjects().filter(canSee);
  const { rows, loaded, failed, retry } = useRows(ws);
  const allSessions = useCodingSessions(ws).data ?? [];
  const row = rows.find((r) => r.id === threadId);
  // A conversation just started isn't listed yet: its address says where it is.
  const thread =
    threadId && (row || across || projectKey)
      ? { id: threadId, projectId: row ? row.projectId : across ? null : (projByKey(projectKey!)?.id ?? null), title: row?.title ?? "" }
      : null;
  // Conversations waiting on a decision, Kai's in them included.
  const waitingIn = new Set(allSessions.filter((c) => c.thread_id && WAITING.includes(c.status)).map((c) => c.thread_id));
  const threads = rows
    .filter((r) => !q || r.title.toLowerCase().includes(q))
    .map((r) => (waitingIn.has(r.id) ? { ...r, waiting: true } : r))
    .sort((a, b) => b.at - a.at);
  const hasSel = Boolean(threadId || projectKey || across || search.get("q") || search.get("new"));
  // Column widths, dragged by their edges and kept in this browser.
  const [listW, setListW] = useStoredSize("dotrix.chat.listWidth", 300, 220, 480);
  // The list folds to a rail (like the sidebar) to give the conversation the room; not on phones.
  const [listMinSet, setListMin] = useStoredFlag("dotrix.chat.listMin");
  const listMin = listMinSet && !window.matchMedia("(max-width: 900px)").matches;
  // A project's conversations, the latest first. Kai's sessions are listed in Codes.
  const itemsOf = (projectId: string) => threads.filter((t) => t.projectId === projectId).map((t) => <ThreadRow key={t.id} row={t} on={threadId === t.id} />);
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
                <Ic n="square-pen" s={16} />
              </button>
            </div>
          ) : (
            <>
              <Splitter dir="col" className="edge-r" label="Resize the list" onDrag={(d) => setListW((w) => w + d)} />
              <div style={{ padding: "18px 16px 8px" }} className="row">
                <h1 style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600, letterSpacing: "-.015em" }}>Chat</h1>
                <span className="sp" />
                <button className="ibtn ibtn-sm chat-fold" onClick={() => setListMin(true)} aria-label="Hide the list" data-tip="Hide the list">
                  <Ic n="panel-left-close" s={15} />
                </button>
              </div>
              <div className="chat-new">
                <button className="btn btn-secondary" onClick={() => open("new=1")}>
                  <Ic n="square-pen" s={14} /> New chat
                </button>
              </div>
              <div style={{ padding: "0 14px 8px" }}>
                <div className="inwrap">
                  <Ic n="search" s={13} />
                  <input
                    className="input search-sm"
                    style={{ width: "100%" }}
                    placeholder="Find a conversation"
                    value={S.ui.chatQ}
                    onChange={(e) => ((S.ui.chatQ = e.target.value), render())}
                    aria-label="Find"
                  />
                </div>
              </div>
              <nav className="chat-list" aria-label="Conversations">
                {ps.map((p) => {
                  const list = itemsOf(p.id);
                  if (!list.length && q) return null;
                  return (
                    <Group key={p.id} title={p.name} color={pColor(p)} onNew={() => open(`project=${p.key}`)}>
                      {list.length ? (
                        list
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
              </nav>
            </>
          )}
        </aside>
        <section className="chat-main">
          {!isLive() && threadId ? (
            <Pending text="This conversation isn't available in the demo. Review the request in Inbox." inbox />
          ) : threadId ? (
            thread ? (
              <Conversation key={thread.id} id={thread.id} projectId={thread.projectId} title={thread.title} />
            ) : failed ? (
              <Pending text="The conversation couldn't be loaded." onRetry={retry} />
            ) : (
              <Pending text={loaded ? MISSING_THREAD : "Loading the conversation…"} loading={!loaded} />
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
