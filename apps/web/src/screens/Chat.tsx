import { useAtPicker } from "../components/AtPicker";
import { ActionButton } from "@dotrix/ui/components/action-button";
import { Suggestions } from "@dotrix/ui/components/ai-elements/suggestion";
import { ChatMessage } from "@dotrix/ui/components/chat/chat-message";
import { ChatLoadingState } from "@dotrix/ui/components/chat/chat-states";
import { ChatTranscriptReply } from "@dotrix/ui/components/chat/chat-transcript-reply";
import { ChatTypingIndicator } from "@dotrix/ui/components/chat/chat-typing-indicator";
import { Select, SelectContent, SelectField, SelectItem, SelectTrigger, SelectValue } from "@dotrix/ui/components/select";
import {
  ChatComposer,
  ChatComposerInput,
  ChatLayout,
  ChatMessageList,
  ChatSendButton,
  CodingOptions,
  ComplexSelector,
  DesignButton,
  InlineCode,
  Lightbox,
  Selector,
} from "../components/chat-ui";
// dotrix's workspace Chat: conversations grouped by project (and
// "General"), a new chat with project, agent, and model; replies with what the agent did
// and the changes it proposes; and a card for each of Kai's sessions started from a conversation, linking to it in Codes.
// The coding session itself (its turns, the new-session form, the list) is screens/Coding.tsx, built from the pieces exported here.
// Conversations and sessions come from the API (TanStack Query); projects, people, and issues still from the store.
// URL: ?thread=ID&project=KEY (or &across=1), ?project=KEY (new chat), ?q=, ?agent=. Older ?session= and ?tab=coding links open in Codes.
import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type ComponentProps } from "react";

import {
  isActive,
  modelName,
  providerName,
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
  MODE_ICONS,
  APPROVAL_MODES,
  type AgentId,
  type ApprovalMode,
  type ChatRuntime,
  type Plan,
  type Run,
  type RunStreamState,
  type WorkMode,
} from "@/lib/agent";
import {
  isActive as isOpenTurn,
  useCodingAvailability,
  useCodingSession,
  useCodingSessionStream,
  useCodingSessions,
  useDecideCoding,
  useFollowUp,
  useCodingInputs,
  useSendCodingInput,
  useCancelCodingInput,
  useStartCoding,
  useRecoverCoding,
  useRevertCoding,
  statusLabel,
  useStopCoding,
  type CodingRun,
  type CodingSession,
} from "@/lib/coding";
import { useCrossConversations, useCrossStream, useCrossThread, useSendCross, useStopCross } from "@/lib/conversations";
import type { Scope } from "@/lib/issues";
import { CiSensitiveNote } from "../components/CiSensitiveNote";
import { LimitNotice } from "../components/LimitNotice";
import { allowed, approvalModes, defaultApproval, canManageIssues } from "../core/can";
import { openPop, openTask } from "../core/actions";
import { desktop, desktopBrowser, useBrowserSettings, useDesktopRunners, type DesktopRunner } from "../core/desktop";
import { Ic } from "../core/icons";
import { newProject } from "../core/more";
import { go, useRoute } from "../core/nav";
import { ago, greeting } from "../core/utils";
import { isLive, live } from "../data/live";
import { useLiveAllTasks, useLiveKnowledgeFiles } from "../../lib/workspace-data";
import { D, S, canSee, me, proj, projByKey, render, who } from "../data/store";
import { useAgents, useProjects } from "../data/lists";
import { useAllTasks } from "../data/tasks";
import { Markdown } from "@/components/markdown";
import { PublishChatOutcome } from "../components/PublishChatOutcome";
import { ChangeCard } from "../components/Changes";
import { RunApprovals } from "../components/RunApprovals";
import { openDocument } from "./Knowledge";
import { Av, PIcon } from "../ui/helpers";
import { moodOf } from "../core/presence";
import { Face } from "../ui/face";
import { toast } from "../ui/toast";
import { CODING_AGENT, CODING_TOOLS } from "../core/team";
import { CODING_VIEWS, CodingPanes, codingPaneType, newCodingPane, useActivePane, type CodingPaneId, type CodingView } from "../components/SidePanel";
import { BackgroundTasks, KaiBackground } from "../components/BackgroundTasks";
import { SessionDetails, modeName } from "../components/SessionDetails";
import { useConversationTasks, useReviewRunQueries, useReviewRuns, type SpecialistTask } from "@/lib/team";
import { SessionTabs } from "../components/SessionTabs";
import { ChoiceCard, type Choice } from "../components/ChoiceCard";
import {
  ChainOfThought,
  Checkpoint,
  Citation,
  ContextUsage,
  PlanSteps,
  Queue,
  Reasoning,
  RunFailure,
  Sources,
  Subagents,
  ToolCalls,
  TraceList,
  type Usage,
} from "../components/AgentTrace";
import { useStoredText } from "../ui/splitter";
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";

const agentName = (h: string) =>
  CODING_TOOLS.some((tool) => tool.id === h || tool.id === `agent:${h}`) ? CODING_AGENT.name : (D().agents.find((a) => a.handle === h)?.name ?? h);
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
  ["sparkles", "Help me explore an idea"],
  ["message-circle", "Help me think through a question"],
];

// What fx does, under its composer.

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
  const own = useWorkspaceThreads(isLive() ? ws : undefined);
  const cross = useCrossConversations(isLive() ? ws : undefined);
  const rows: Row[] = !isLive()
    ? D().threads.map((thread) => ({
        id: thread.id,
        title: thread.title,
        at: thread.at,
        projectId: thread.project,
        projectKey: thread.project ? (proj(thread.project)?.key ?? null) : null,
        projectKeys: (thread.projects ?? []).flatMap((id) => proj(id)?.key ?? []),
        waiting: thread.messages.some((message) => message.changes?.some((change) => change.status === "pending")),
      }))
    : [
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
    loaded: !isLive() || (own.isFetched && cross.isFetched),
    failed: isLive() && (own.isError || cross.isError),
    retry: () => {
      void own.refetch();
      void cross.refetch();
    },
  };
}

const threadSearch = (r: Pick<Row, "id" | "projectKey">) => (r.projectKey ? `thread=${r.id}&project=${r.projectKey}` : `thread=${r.id}&across=1`);

function ThreadRow({ row, on, onPick }: { row: Row; on: boolean; onPick: () => void }) {
  return (
    <ActionButton
      className={`sitem ${on ? "on" : ""}`}
      style={{ height: "auto", padding: "6px 8px", alignItems: "flex-start" }}
      aria-label={`${row.title} · ${ago(row.at)}`}
      onClick={() => {
        onPick();
        open(threadSearch(row));
      }}
    >
      <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
        <span className="trunc" style={{ display: "block", fontWeight: on ? 500 : 400 }}>
          {row.title}
        </span>
        <span className="faint" style={{ fontSize: 11.5 }}>
          {row.projectId ? `${proj(row.projectId)?.name ?? row.projectKey} · ` : row.projectKeys.length > 0 && `${row.projectKeys.join(", ")} · `}
          {ago(row.at)}
        </span>
      </span>
      {row.waiting && <span className="sdot" style={{ background: "var(--amber)", marginTop: 6 }} aria-label="Waiting for a decision" />}
    </ActionButton>
  );
}

export const STATUS: Record<CodingSession["status"], [string, string]> = {
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

/** Shared session chrome keeps sample and live panes on the same responsive layout. */
export function SessionHeader({ className = "", children, ref, ...props }: ComponentProps<"div">) {
  const ownRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const head = ownRef.current;
    const conv = head?.closest<HTMLElement>(".conv");
    if (!head || !conv) return;
    const update = () => conv.style.setProperty("--cs-head-h", `${head.offsetHeight}px`);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(head);
    return () => ro.disconnect();
  }, []);
  return (
    <div
      {...props}
      ref={(node) => {
        ownRef.current = node;
        if (typeof ref === "function") ref(node);
        else if (ref) ref.current = node;
      }}
      className={`row cs-head ${className}`}
    >
      {children}
    </div>
  );
}

export function SessionRow({ cs, on, onPick }: { cs: CodingSession; on: boolean; onPick: () => void }) {
  const [label0, c] = STATUS[cs.status];
  const label = cs.location === "local" && cs.status === "queued" ? "Waiting for your computer" : label0;
  const title = cs.title ?? cs.issue_title;
  return (
    <div className={`cs-row ${on ? "on" : ""}`}>
      <button
        className={`sitem ${on ? "on" : ""}`}
        aria-label={`${cs.issue_key} ${title} · ${label}`}
        title={title}
        onClick={() => {
          onPick();
          openCoding(`session=${cs.session_id}`);
        }}
      >
        <span className="cs-row-copy">
          <span className="cs-row-title">
            {cs.pinned && <Ic n="pin" s={12} cls="cs-pin" />}
            {cs.thread_id && (
              <span className="faint" aria-label="Started from a conversation">
                <Ic n="message-square" s={12} />
              </span>
            )}
            {title}
          </span>
          <span className="cs-row-foot">
            <span className="cs-row-meta">
              {cs.issue_key && <span className="mono">{cs.issue_key} ·</span>}
              <span>{ago(ms(cs.updated_at))}</span>
              {cs.pr_number && <span>· PR #{cs.pr_number}</span>}
            </span>
            <span className={`badge ${c}`}>{label}</span>
          </span>
        </span>
      </button>
      <ActionButton
        className="ibtn ibtn-xs cs-more"
        onClick={(e) => openPop(e.currentTarget, "session", { id: cs.session_id, session: cs })}
        aria-label={`More for ${cs.issue_key || title}`}
        aria-haspopup="menu"
      >
        <Ic n="ellipsis" s={14} />
      </ActionButton>
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
    <div className="change" role="group" aria-label={`Kai on ${cs.issue_key}`} style={{ margin: "4px 0 12px" }}>
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
            <InlineCode>{cs.branch}</InlineCode>
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
            <LineCounts files={files} onClick={() => openCoding(`session=${cs.session_id}&turn=${latest.id}&panel=changes`)} tip="Open the changes in Code" />
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
            <ActionButton className="btn btn-sm btn-ghost" disabled={decide.isPending} onClick={() => decide.mutate({ runId: latest.id, decision: "reject" })}>
              {ready ? "Discard changes" : "Reject"}
            </ActionButton>
            <ActionButton
              className="btn btn-sm btn-primary"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ runId: latest.id, decision: "approve" })}
            >
              {ready ? "Accept and push" : "Approve"}
            </ActionButton>
          </>
        )}
        {latest?.can_revert && (
          <ActionButton className="btn btn-sm btn-ghost" disabled={revert.isPending} onClick={() => revert.mutate(latest.id)}>
            Revert this turn
          </ActionButton>
        )}
        {latest?.can_stop && (
          <ActionButton className="btn btn-sm btn-secondary" disabled={stop.isPending} onClick={() => stop.mutate(latest.id)}>
            Stop
          </ActionButton>
        )}
        {latest?.can_recover && (
          <ActionButton className="btn btn-sm btn-secondary" disabled={recover.isPending} onClick={() => recover.mutate({ runId: latest.id, action: "check" })}>
            Check and recover
          </ActionButton>
        )}
        <span className="sp" />
        <ActionButton className="btn btn-sm btn-ghost" onClick={() => openCoding(`session=${cs.session_id}`)}>
          Open in Code
          <Ic n="arrow-right" s={12} />
        </ActionButton>
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

export function Message({
  m,
  projectId,
  tag,
  sources,
  usage,
  children,
}: {
  m: Msg;
  projectId: string | null;
  tag?: string;
  /** The pages a reply read (S1, S2, …): its "[S1]" become inline citations, and they're listed under it. */
  sources?: Run["sources"];
  /** A reply's tokens, shown to whoever asked for it (and owners and admins). */
  usage?: Usage & { mine: boolean };
  children?: React.ReactNode;
}) {
  const w = who(m.by);
  const { items: agents } = useAgents();
  const agent = m.role === "agent" ? agents.find((a) => a.handle === m.by) : null;
  const liveTasks = useLiveAllTasks(live.ws?.id, isLive());
  const liveDocs = useLiveKnowledgeFiles(isLive() && live.ws && projectId ? { workspaceId: live.ws.id, projectId } : undefined, isLive() && m.role === "agent");
  const refs =
    m.role === "agent" ? refsOf(projectId, m.text, m.activity, isLive() ? liveTasks : undefined, isLive() ? liveDocs : undefined) : { tasks: [], docs: [] };
  const p = proj(projectId ?? "");
  const admin = me()?.role === "Owner" || me()?.role === "Admin";
  if (m.role === "user")
    return (
      <>
        <ChatMessage
          data-sender="user"
          side="outgoing"
          className="chat-msg dotrix-message"
          footer={
            <div className="chat-ask-meta">
              {tag && <span className="badge">{tag}</span>}
              {m.by !== D().me && <span>{w?.name ?? "Someone"} ·</span>}
              <time>{ago(m.at)}</time>
              <ActionButton
                className="ibtn ibtn-xs"
                onClick={() => copyText(m.text)}
                aria-label={m.by === D().me ? "Copy what you wrote" : "Copy message"}
                data-tip="Copy"
              >
                <Ic n="copy" s={13} />
              </ActionButton>
              <Av id={m.by} cls="sm" tip={false} />
            </div>
          }
        >
          {m.text}
        </ChatMessage>
        {children}
      </>
    );
  return (
    <ChatTranscriptReply
      data-sender="assistant"
      className="chat-msg dotrix-message"
      avatar={<Face c={agent?.c ?? "#57544E"} size={24} mood="idle" />}
      author={
        <div className="who">
          <b>{agent?.name ?? agentName(m.by)}</b>
          {agent && <span className="role">{agent.role}</span>}
          <time>{ago(m.at)}</time>
          {tag && <span className="badge">{tag}</span>}
          {usage && (usage.mine || admin) ? (
            <ContextUsage usage={usage} />
          ) : m.tokens && admin ? (
            <span className="faint">{(m.tokens / 1000).toFixed(1)}k tokens</span>
          ) : null}
        </div>
      }
      beforeBody={m.activity?.length ? <ChainOfThought steps={m.activity} /> : undefined}
      bubbleProps={{ className: "md" }}
      body={
        m.text ? (
          <Markdown
            cite={
              sources?.length
                ? (label) => {
                    const source = sources.find((x) => x.label === label);
                    return source ? <Citation source={source} /> : undefined;
                  }
                : undefined
            }
          >
            {m.text}
          </Markdown>
        ) : undefined
      }
    >
      {m.role === "agent" && sources?.length ? <Sources sources={sources} /> : null}
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
    </ChatTranscriptReply>
  );
}

/** A run as two messages: what was asked, and the agent's reply (as it's written, while it works). */
function RunMessages({ run, projectId, scope, stream }: { run: Run; projectId: string | null; scope: Scope | undefined; stream: RunStreamState | null }) {
  const cont = useContinueRun(scope);
  const limited = run.error_kind === "model_limit";
  const interrupted = run.status === "failed" && run.error_kind === "interrupted";
  const failed = ["failed", "cancelled", "blocked"].includes(run.status) && !limited;
  const text = stream ? stream.text : (run.reply ?? "");
  const reply: Msg = {
    id: `${run.id}-reply`,
    role: "agent",
    by: handleOf(run.agent),
    at: ms(run.finished_at ?? run.updated_at),
    // A failure is said as one, not as the agent's words (the provider's message can be anything: a quota, a refusal).
    text: failed ? (wasStopped(run) ? "Stopped." : "") : text,
    tokens: (run.input_tokens ?? 0) + (run.output_tokens ?? 0) || undefined,
  };
  const shows = !stream || stream.text;
  const broke = failed && !wasStopped(run);
  return (
    <>
      {run.source !== "coding_outcome" && (
        <Message
          m={{ id: run.id, role: "user", by: run.requested_by_id ?? D().me, at: ms(run.created_at), text: run.message || runTitle(run) }}
          projectId={projectId}
          tag={WORK_MODES.find(([v]) => v === run.work_mode)?.[1]}
        />
      )}
      {shows && (reply.text || run.approvals?.length || limited || broke) ? (
        <Message
          m={reply}
          projectId={projectId}
          sources={stream ? undefined : run.sources}
          usage={
            stream
              ? undefined
              : {
                  input: run.input_tokens,
                  cached: run.cached_input_tokens,
                  output: run.output_tokens,
                  calls: run.model_calls,
                  complete: run.usage_complete,
                  model: run.model ? modelName(run.model) : null,
                  mine: run.requested_by_id === D().me,
                }
          }
        >
          {stream && stream.activity && (
            <Trace className="agent-trace" aria-live="polite">
              <TraceLine status="running">
                <TraceIcon>
                  <Ic n="spinner-gap" cls="animate-spin" />
                </TraceIcon>
                <TraceTitle>{stream.activity}</TraceTitle>
              </TraceLine>
            </Trace>
          )}
          {broke && <RunFailure who={agentName(handleOf(run.agent))} message={run.error} />}
          {scope && !stream && run.status === "completed" && run.requested_by_id === D().me && !!run.reply && (
            <PublishChatOutcome scope={scope} runId={run.id} reply={run.reply} />
          )}
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
              <ActionButton className="btn btn-sm btn-secondary" disabled={cont.isPending} onClick={() => cont.mutate({ runId: run.id, whenReset: false })}>
                <Ic n="play" s={12} />
                Continue
              </ActionButton>
            </div>
          )}
        </Message>
      ) : null}
    </>
  );
}

/** What the agents did for a reply (kept after the run): a Subagent line each, folded until asked for. */
function SpecialistTasks({ tasks, scope }: { tasks: SpecialistTask[]; scope: Scope | undefined }) {
  return <Subagents tasks={tasks} approval={(task) => <TaskApproval scope={scope} id={task.id} />} />;
}

function TaskApproval({ scope, id }: { scope: Scope | undefined; id: string }) {
  const run = useReviewRuns(scope, [id])[0];
  return run ? <RunApprovals run={run} scope={scope} /> : null;
}

/** A reply's steps and what its model thought, kept after the run: loaded when first opened. */
function RunSteps({ scope, runId }: { scope: Scope | undefined; runId: string }) {
  const [open, setOpen] = useState(false);
  const steps = useRunSteps(scope, runId, open);
  return (
    <div className="agent-trace-steps">
      <ChainOfThought
        title="Steps"
        steps={steps.data?.steps ?? []}
        thinking={steps.data?.thinking || undefined}
        loading={steps.isLoading}
        onOpenChange={setOpen}
      />
    </div>
  );
}

/** A version of the conversation's plan; the latest can be built (a Build message naming its version). */
function PlanCard({ plan, latest, busy, onBuild }: { plan: Plan; latest: boolean; busy: boolean; onBuild: () => void }) {
  return (
    <div className="change" role="group" aria-label={`Plan version ${plan.version}`} style={{ margin: "4px 0 12px" }}>
      <div className="change-h">
        <Ic n="list-checks" s={14} />
        <b style={{ fontWeight: 500 }}>{plan.title}</b>
        <span className="badge">Plan v{plan.version}</span>
      </div>
      <div className="agent-plan-body">
        <p style={{ margin: 0 }}>{plan.summary}</p>
        <PlanSteps
          title={`${plan.tasks.length} task${plan.tasks.length === 1 ? "" : "s"}`}
          steps={plan.tasks.map((t) => ({
            title: t.title,
            detail: t.detail || undefined,
            note: t.depends_on.length ? `after ${t.depends_on.join(", ")}` : undefined,
          }))}
        />
        {plan.execution && (
          <details>
            <summary>
              Implementation details · {plan.execution.repository} · {plan.execution.base_sha.slice(0, 8)}
            </summary>
            <TraceList title="Constraints" items={plan.execution.constraints ?? []} icon="question" />
            <TraceList title="Out of scope" items={plan.execution.exclusions ?? []} icon="question" />
            {plan.execution.tasks.map((task) => (
              <div key={task.key}>
                <p>
                  <b>
                    Task {task.task_number}: {task.key}
                  </b>
                </p>
                <TraceList title="Owned paths" items={task.owned_paths} icon="file" />
                <p>{task.instructions}</p>
                <TraceList title="Verification" items={(task.checks ?? []).map((check) => `${check.command} — ${check.expected}`)} icon="check-square" />
                <TraceList title="Stop conditions" items={task.stop_conditions} icon="question" />
              </div>
            ))}
          </details>
        )}
        <TraceList title="Acceptance criteria" items={plan.acceptance_criteria} icon="check-square" />
        <TraceList title="Open questions" items={plan.open_questions} icon="question" />
      </div>
      {latest && (
        <div className="change-f">
          <span className="faint" style={{ fontSize: 12 }}>
            Building asks for your approval before anything changes, and Kai's coding before it starts.
          </span>
          <span className="sp" />
          <ActionButton className="btn btn-sm btn-primary" disabled={busy} onClick={onBuild}>
            <Ic n="hammer" s={12} />
            Build this plan
          </ActionButton>
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
  plain = false,
  variant = "default",
  groupOf,
}: {
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  label: string;
  lead?: React.ReactNode;
  /** Compact text trigger for the composer and its options menu. */
  plain?: boolean;
  variant?: "default" | "ghost";
  /** Options under headings (the Model Selector's providers): each option's group, "" for none. */
  groupOf?: (value: string) => string;
}) {
  const grouped = groupsOf(options, groupOf);
  const choices = grouped.map(([title, rows]) => ({
    type: "section" as const,
    title: title || undefined,
    options: rows.map(([value, label]) => ({ value, label })),
  }));
  return (
    <span className={plain ? "dotrix-inline-picker" : undefined} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      {lead}
      <Selector label={label} isLabelHidden value={value} onChange={onChange} options={choices} hasSearch={options.length > 8} size="sm" variant={variant} />
    </span>
  );
}

/** Standalone Approval mode selector rendered directly in the composer toolbar (not inside +). */
export function ApprovalPick({
  value,
  onChange,
  options,
}: {
  value: ApprovalMode;
  onChange: (value: ApprovalMode) => void;
  options: [ApprovalMode, string, string][];
}) {
  const tip = options.find(([v]) => v === value)?.[2];
  return (
    <span className="cmp-approval-wrap" data-tip={tip}>
      <Select value={value} onValueChange={(next) => onChange(next as ApprovalMode)}>
        <SelectTrigger size="sm" variant="ghost" aria-label="Approvals" className={`cmp-approval-trigger ${value === "auto" ? "amber" : ""}`}>
          <Ic n="shield-check" s={12} />
          <SelectValue />
        </SelectTrigger>
        <SelectContent aria-label="Approvals">
          {options.map(([val, label]) => (
            <SelectItem key={val} value={val}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </span>
  );
}

/** Options in their groups, in the order each group first appears; one unnamed group without `groupOf`. */
function groupsOf(options: [string, string][], groupOf?: (value: string) => string): [string, [string, string][]][] {
  if (!groupOf) return [["", options]];
  const out = new Map<string, [string, string][]>();
  for (const o of options) {
    const g = groupOf(o[0]);
    out.set(g, [...(out.get(g) ?? []), o]);
  }
  return out.size > 1 ? [...out] : [["", options]];
}

/** Where a new session codes, as Claude Code's environment menu: this computer (its folder for the
 *  project, or a computer running `dotrix runner`), the cloud sandbox, and, in the desktop app, a folder to
 *  add. */
function WhereItCodes({
  location,
  setWhere,
  cloudReady,
  cloudWhy,
  localReady,
  localName,
  localWhy,
  folder,
  canAdd,
  adding,
  onAdd,
  onClose,
}: {
  location: "cloud" | "local";
  setWhere: (where: "cloud" | "local") => void;
  cloudReady: boolean;
  cloudWhy?: string | null;
  localReady: boolean;
  localName?: string | null;
  localWhy?: string | null;
  folder?: DesktopRunner;
  canAdd: boolean;
  adding: boolean;
  onAdd: () => void;
  onClose: () => void;
}) {
  const folderName = folder ? folder.folder.split(/[\\/]/).filter(Boolean).pop() : null;
  const localLabel = folderName ?? localName ?? "Your computer";
  const starting = adding || folder?.state === "starting";
  const choose = (where: "cloud" | "local") => {
    setWhere(where);
    onClose();
  };
  return (
    <div className="composer-environment-options" role="group" aria-label="Where it codes">
      <span className="composer-menu-heading">Environment</span>
      {localReady || folder ? (
        <DesignButton
          label={
            <>
              <span>{localReady ? localLabel : `${localLabel} (${starting ? "Starting…" : folder?.state === "failed" ? "Stopped" : "Not ready"})`}</span>
              {location === "local" && <Ic n="check" s={14} cls="composer-menu-check" />}
            </>
          }
          variant="ghost"
          className="composer-menu-option"
          icon={<Ic n="laptop" s={15} />}
          aria-pressed={location === "local"}
          isDisabled={!localReady}
          data-tip={folder?.folder ?? localWhy ?? undefined}
          onClick={() => choose("local")}
        />
      ) : (
        !canAdd && (
          <span className="composer-menu-note" title={localWhy ?? undefined}>
            Run <InlineCode>dotrix runner</InlineCode> in your checkout, or use the desktop app
          </span>
        )
      )}
      {canAdd && (
        <DesignButton
          label={folder ? (folder.state === "failed" ? "Choose the folder again" : "Choose another folder") : "Add a folder"}
          variant="ghost"
          className="composer-menu-option"
          icon={<Ic n="folder-plus" s={15} />}
          isDisabled={starting}
          onClick={() => {
            onAdd();
            choose("local");
          }}
        />
      )}
      <DesignButton
        label={
          <>
            <span>Cloud sandbox</span>
            {location === "cloud" && <Ic n="check" s={14} cls="composer-menu-check" />}
          </>
        }
        variant="ghost"
        className="composer-menu-option"
        icon={<Ic n="cloud" s={15} />}
        aria-pressed={location === "cloud"}
        data-tip={cloudReady ? "In a sandbox on the platform" : (cloudWhy ?? undefined)}
        onClick={() => choose("cloud")}
      />
    </div>
  );
}

export const SAMPLE_COMPOSER_MODELS = ["openai:gpt-5.4", "anthropic:claude-sonnet-5-5"];

/** New sessions choose a model; existing sessions keep the model admitted for their run. */
export function ComposerModel({
  model,
  models,
  onChange,
  empty = "No models connected",
}: {
  model?: string | null;
  models?: [string, string][];
  onChange?: (model: string) => void;
  empty?: string;
}) {
  return (
    <span className="cmp-model composer-model">
      {onChange && models?.length ? (
        <Pick plain variant="ghost" value={model ?? ""} onChange={onChange} options={models} label="Model" groupOf={providerName} />
      ) : (
        <DesignButton label={model ? modelName(model) : empty} aria-label="Model" variant="ghost" size="sm" className="cmp-model-static" isDisabled />
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
  onStop,
  stopDisabled = false,
  modeOptions = WORK_MODES,
  disabled = false,
  draftOnly = false,
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
  onStop?: () => void;
  stopDisabled?: boolean;
  modeOptions?: typeof WORK_MODES;
  disabled?: boolean;
  draftOnly?: boolean;
}) {
  const approvals = APPROVAL_MODES.filter(([v]) => approvalModes().includes(v));
  const [text, setText] = useState(initial);
  const [submitting, setSubmitting] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const atPicker = useAtPicker({
    text,
    setText,
    ref,
    projects: contexts,
    project: context,
    onProject: setContext,
    modes: setMode ? modeOptions : undefined,
    mode,
    onMode: setMode,
  });
  const a = useAgents().items.find((x) => x.handle === agent);
  // "+" offers the work modes (projects already live in the context card and @-mentions); Nova always answers.
  const choices = useMemo(
    () => (setMode ? modeOptions.map(([id, label]) => ({ id: `mode:${id}`, label, auxiliaryData: { group: "Modes" } })) : []),
    [setMode, modeOptions],
  );
  const choose = (id: string) => {
    if (id.startsWith("mode:")) setMode?.(id.slice(5) as WorkMode);
    return "";
  };
  const hasRuntimeRow = Boolean(runtime && (setRuntime || runtime === "fx"));
  const hasAgentChip = Boolean(agent !== "auto" && a && setAgent);
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);
  const send = async () => {
    const q = text.trim();
    if (!q || S.ui.offline || disabled || draftOnly || submitting) return;
    setSubmitting(true);
    try {
      await onSend(q, agent);
      setAgent?.("auto");
      setText("");
      atPicker.close();
    } catch {
      // The mutation reports the error; keep the person's draft for retry.
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <div className="dotrix-composer-wrap">
      {atPicker.menu}
      <ChatComposer
        onSubmit={() => {
          void send();
        }}
        value={text}
        isDisabled={disabled || submitting}
        input={
          <ChatComposerInput
            textareaRef={ref}
            value={text}
            onChange={(event) => atPicker.onChange(event.currentTarget)}
            placeholder={placeholder}
            label="Message"
            pasteAsToken={false}
            hasHistory={false}
            onKeyDown={(event) => {
              if (!event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229 && atPicker.onKeyDown(event)) return;
              // Enter sends through Dotrix's own path, which clears only
              // after the server accepts the message, retaining failed drafts.
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
                event.preventDefault();
                void send();
              }
            }}
            status={submitting ? "sending" : disabled ? "waiting" : "ready"}
            isDisabled={submitting || disabled}
            onSubmit={() => {
              void send();
            }}
          />
        }
        footerActions={
          <div className="cmp-footer-left">
            <ComplexSelector
              label="Chat options"
              isLabelHidden
              value=""
              placement="above"
              alignment="start"
              renderTrigger={(triggerProps) => (
                <DesignButton
                  {...triggerProps}
                  role="button"
                  label="Chat options"
                  className="cmp-plus-btn"
                  variant="ghost"
                  size="sm"
                  isIconOnly
                  icon={<Ic n="plus" s={16} />}
                />
              )}
            >
              {(_value, _change, close) => (
                <div className="composer-options-menu">
                  {choices.map((choice, index) => {
                    const selected = choice.id === `mode:${mode}`;
                    const groupChanged = index === 0 || choices[index - 1]?.auxiliaryData.group !== choice.auxiliaryData.group;
                    return (
                      <Fragment key={choice.id}>
                        {groupChanged && index > 0 && <div className="composer-menu-sep" />}
                        {groupChanged && <span className="composer-menu-heading">{choice.auxiliaryData.group}</span>}
                        <DesignButton
                          label={
                            <>
                              <span>{choice.label}</span>
                              {selected && <Ic n="check" s={14} cls="composer-menu-check" />}
                            </>
                          }
                          variant="ghost"
                          className="composer-menu-option"
                          icon={<Ic n={MODE_ICONS[choice.id.slice(5) as WorkMode]} s={15} />}
                          aria-pressed={selected}
                          onClick={() => {
                            choose(choice.id);
                            close();
                            ref.current?.focus();
                          }}
                        />
                      </Fragment>
                    );
                  })}
                  {choices.length === 0 && (
                    <span className="composer-menu-note">{contexts ? "Choose a project above to pick a work mode" : "General chat"}</span>
                  )}
                  {hasRuntimeRow && (
                    <>
                      <div className="composer-menu-sep" />
                      {setRuntime ? (
                        <div className="composer-menu-row">
                          <span className="composer-menu-row-label">Runtime</span>
                          <Pick
                            plain
                            value={runtime!}
                            onChange={(v) => setRuntime(v as ChatRuntime)}
                            options={[
                              ["deepagents", "Standard"],
                              ["fx", "fx"],
                            ]}
                            label="Chat runtime"
                          />
                        </div>
                      ) : (
                        runtime === "fx" && (
                          <div className="composer-menu-row">
                            <span className="composer-menu-row-label">Runtime</span>
                            <span data-tip="This conversation runs on fx">fx</span>
                          </div>
                        )
                      )}
                    </>
                  )}
                  {hasAgentChip && a && setAgent && (
                    <>
                      <div className="composer-menu-sep" />
                      <button className="cmp-chip" onClick={() => setAgent("auto")} aria-label={`Remove request to involve ${a.name}`}>
                        Involve {a.name} <Ic n="x" s={10} />
                      </button>
                    </>
                  )}
                </div>
              )}
            </ComplexSelector>
            {mode && (
              <span
                className={`cmp-status-badge ${mode === "build" || mode === "plan" ? "accent" : ""}`}
                aria-label={`Work mode: ${WORK_MODES.find(([v]) => v === mode)?.[1] ?? mode}`}
                data-tip="Work mode"
              >
                <Ic n={MODE_ICONS[mode]} s={12} />
                <span>{WORK_MODES.find(([v]) => v === mode)?.[1] ?? mode}</span>
              </span>
            )}
            {mode &&
              approval &&
              (setApproval && approvals.length > 1 ? (
                <ApprovalPick value={approval} onChange={setApproval} options={approvals} />
              ) : (
                <span
                  className={`cmp-status-badge ${approval === "auto" ? "amber" : ""}`}
                  aria-label={`Approval mode: ${APPROVAL_MODES.find(([v]) => v === approval)?.[1] ?? approval}`}
                  data-tip="Approvals"
                >
                  <Ic n="shield-check" s={12} />
                  <span>{APPROVAL_MODES.find(([v]) => v === approval)?.[1] ?? approval}</span>
                </span>
              ))}
            {runtime === "fx" && (
              <span className="cmp-status-badge mono" aria-label="Runtime: fx" data-tip="Chat runtime">
                fx
              </span>
            )}
          </div>
        }
        sendActions={<ComposerModel model={model} models={models} onChange={setModel} empty={setModel ? "No models connected" : "Model not recorded"} />}
        sendButton={
          <>
            {(!onStop || text.trim()) && (
              <ChatSendButton
                onSend={() => {
                  void send();
                }}
                status={submitting ? "sending" : disabled ? "waiting" : "ready"}
                isDisabled={!text.trim() || S.ui.offline || disabled || draftOnly || submitting}
              />
            )}
            {onStop && <ChatSendButton isStopShown onStop={onStop} isDisabled={stopDisabled} aria-label="Stop run" />}
          </>
        }
      />
    </div>
  );
}

function Conversation({ id, projectId, title }: { id: string; projectId: string | null; title: string }) {
  const { items: agents } = useAgents();
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
  const mode = pickedMode ?? lastUser?.work_mode ?? "discuss";
  // How much goes through without waiting: what you picked, else how the conversation was going (if you still may), else the default.
  const [pickedApproval, setApproval] = useState<ApprovalMode | null>(null);
  const lastApproval = lastUser?.approval_mode && approvalModes().includes(lastUser.approval_mode) ? lastUser.approval_mode : null;
  const approval = pickedApproval ?? lastApproval ?? defaultApproval();
  const plans = useThreadPlans(scope, projectId ? id : null, runs.filter((r) => !isActive(r)).length).data ?? [];
  // Kai's sessions started from this conversation, each after the message that started it.
  const coded = (useCodingSessions(ws, Boolean(projectId)).data ?? []).filter((c) => c.thread_id === id);
  const anchorOf = (c: CodingSession) => runs.filter((r) => ms(r.created_at) <= ms(c.started_at)).at(-1)?.id ?? last?.id;
  const latestPlan = plans.at(-1);
  const say = (message: string, m: WorkMode = mode) => {
    if (inputBusy) {
      const kind = awaitingApproval ? "queue" : inputKind;
      const retry = retryInput.current;
      const signature = JSON.stringify([id, projectId, message, kind, m, approval]);
      const client_id = retry?.signature === signature ? retry.client_id : crypto.randomUUID();
      retryInput.current = { signature, client_id };
      return submitInput.mutateAsync({ message, kind, client_id, work_mode: m, approval_mode: approval }).then((queued) => {
        retryInput.current = null;
        // The turn had just finished: this is a new message, not a follow-up.
        if (!queued) return send.mutateAsync({ message, threadId: id, agent, workMode: m, approvalMode: approval }).then(() => {});
      });
    }
    return projectId
      ? send.mutateAsync({ message, threadId: id, agent, workMode: m, approvalMode: approval })
      : sendCross.mutateAsync({ message, thread_id: id, agent });
  };
  const build = (plan: Plan) => {
    setMode("build");
    send.mutate({
      message: `Build plan version ${plan.version}: ${plan.title}`,
      threadId: id,
      agent,
      workMode: "build",
      approvalMode: approval,
      planId: plan.id,
    });
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
        <SessionHeader>
          <ActionButton className="ibtn ibtn-sm cs-back" onClick={() => open("")} aria-label="Back to conversations">
            <Ic n="arrow-left" s={15} />
          </ActionButton>
          <b className="trunc" style={{ fontWeight: 600, fontSize: 13.5 }}>
            {title || (runs[0] ? (runs[0].title ?? runTitle(runs[0])) : "")}
          </b>
          <span className="sp" />
          <ActionButton className="ibtn ibtn-sm" onClick={() => copyText(location.href)} aria-label="Copy link to conversation" data-tip="Copy link">
            <Ic n="link" s={14} />
          </ActionButton>
          {p ? (
            <button className="pillbtn" onClick={() => go("project", { id: p.key, tab: "overview" })}>
              <PIcon p={p} s={12} />
              {p.name}
            </button>
          ) : (
            <span className="pillbtn">
              <Ic n="layers" s={13} />
              {about.join(", ") || "General"}
            </span>
          )}
          <span className="chat-faces hide-m" aria-label="Agents in this conversation">
            {[...new Set(runs.map((r) => handleOf(r.agent)))].map((h) => {
              const ag = agents.find((x) => x.handle === h);
              return ag ? (
                <span key={h} data-tip={`${ag.name} · ${ag.role}`}>
                  <Face c={ag.c} size={20} mood={moodOf(h)} />
                </span>
              ) : null;
            })}
          </span>
        </SessionHeader>
        <ChatLayout
          className="dotrix-chat-layout"
          density={S.prefs.density === "compact" ? "compact" : "balanced"}
          composer={
            <div className="chat-input">
              {inputBusy && (
                <div className="chat-delivery-row">
                  <label htmlFor="chat-delivery-kind">Send as</label>
                  <SelectField
                    id="chat-delivery-kind"
                    size="sm"
                    className="chat-delivery-select"
                    aria-label="Delivery action"
                    value={awaitingApproval ? "queue" : inputKind}
                    onValueChange={(value) => setInputKind(value as "queue" | "steer")}
                    options={[{ value: "queue", label: "Queue after this turn" }, ...(!awaitingApproval ? [{ value: "steer", label: "Steer this turn" }] : [])]}
                  />
                </div>
              )}
              <Queue
                entries={chatInputs
                  .filter(
                    (item) =>
                      item.status === "pending" ||
                      item.status === "sending" ||
                      item.status === "rejected" ||
                      (item.status === "accepted" && item.run_id === working?.id),
                  )
                  .slice(0, 20)
                  .reverse()
                  .map((item) => ({
                    id: item.id,
                    kind: item.kind,
                    message: item.message,
                    status: item.status,
                    error: item.error,
                    said:
                      item.status === "accepted"
                        ? item.kind === "steer"
                          ? "Accepted for the next safe point"
                          : "Queued after this turn"
                        : item.status === "rejected"
                          ? "Not delivered"
                          : item.status === "sending"
                            ? "Sending…"
                            : "Waiting to send",
                    onCancel: item.status === "pending" ? () => cancelInput.mutate(item.id) : undefined,
                    cancelling: cancelInput.isPending,
                  }))}
              />
              <Composer
                placeholder="Ask Nova, or type @ to pick a mode"
                agent={agent}
                model={last?.conversation_model ?? last?.model ?? undefined}
                context={p?.name ?? "General"}
                onSend={(q) => say(q)}
                mode={projectId ? mode : undefined}
                setMode={projectId ? setMode : undefined}
                modeOptions={WORK_MODES}
                runtime={fxPreview ? "fx" : undefined}
                approval={projectId ? approval : undefined}
                setApproval={projectId ? setApproval : undefined}
                onStop={active ? halt : undefined}
                stopDisabled={stop.isPending || stopCross.isPending}
                autoFocus
              />
            </div>
          }
        >
          <ChatMessageList followKey={last?.id}>
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
              {active && !stream.text && (
                <ChatMessage
                  side="incoming"
                  bubble={false}
                  className="chat-msg"
                  author={agentName(agent)}
                  avatar={<Face c={agents.find((a) => a.handle === agent)?.c ?? "#E0A92E"} size={24} mood="working" />}
                >
                  {stream.activity ? (
                    <Trace className="agent-trace" aria-live="polite">
                      <TraceLine status="running">
                        <TraceIcon>
                          <Ic n="spinner-gap" cls="animate-spin" />
                        </TraceIcon>
                        <TraceTitle>{stream.activity}</TraceTitle>
                      </TraceLine>
                    </Trace>
                  ) : (
                    <ChatTypingIndicator label={`${agentName(agent)} is thinking…`} />
                  )}
                  {stream.thinking && <Reasoning text={stream.thinking} live />}
                </ChatMessage>
              )}
            </div>
          </ChatMessageList>
        </ChatLayout>
      </div>
    </div>
  );
}

function NewChat({
  projectKey,
  across,
  q,
  agent0,
  mode0,
}: {
  projectKey: string | null;
  across: boolean;
  q: string;
  agent0: string | null;
  mode0: string | null;
}) {
  const ws = wsId();
  const ps = useProjects().items.filter((p) => canSee(p) && (p.status !== "complete" || p.key === projectKey));
  const [pid, setPid] = useState<string>(across ? "" : (projByKey(projectKey ?? "")?.id ?? ""));
  const [agent, setAgent] = useState(agent0 ?? "auto");
  const models = useModels(ws).data ?? [];
  const [chosen, setModel] = useState<string | null>(null);
  const [mode, setMode] = useState<WorkMode>(mode0 === "plan" ? "plan" : "discuss");
  const [chosenRuntime, setRuntime] = useState<ChatRuntime | null>(null);
  const [approval, setApproval] = useState<ApprovalMode>(defaultApproval());
  const scope = useMemo(() => (ws && pid ? { workspaceId: ws, projectId: pid } : undefined), [ws, pid]);
  const runtimeOptions = useChatRuntimeOptions(scope).data;
  const fxModels = models.filter((m) => m.source === "personal" && runtimeOptions?.fx_providers.includes(m.provider));
  const runtime: ChatRuntime = !pid ? "deepagents" : (chosenRuntime ?? (runtimeOptions?.fx_available && fxModels.length > 0 ? "fx" : "deepagents"));
  const availableModels = runtime === "fx" ? fxModels : models;
  const liveChat = isLive();
  const modelOptions = liveChat
    ? availableModels.map((item): [string, string] => [item.id, modelName(item.id, item.name)])
    : SAMPLE_COMPOSER_MODELS.map((id): [string, string] => [id, modelName(id)]);
  const model = modelOptions.find(([id]) => id === chosen)?.[0] ?? modelOptions[0]?.[0] ?? "";
  const unavailable = runtime === "fx" && !model;
  const send = useSendMessage(scope);
  const sendCross = useSendCross(ws);
  const start = (text: string, a: string) => {
    if (!liveChat) return;
    const body = { agent: a as AgentId, model: model || null };
    const started = pid
      ? send
          .mutateAsync({ message: text, threadId: null, ...body, workMode: mode, approvalMode: approval, chatRuntime: runtime })
          .then((run) => `thread=${run.thread_id}&project=${proj(pid)?.key}`)
      : sendCross.mutateAsync({ message: text, thread_id: null, project_ids: [], ...body }).then((run) => `thread=${run.thread_id}&across=1`);
    started.then(open, () => {});
  };
  const sugg = pid ? SUGGESTIONS : ACROSS;
  return (
    <div className="conv new-conversation">
      <div className="ns">
        <div className="ns-mid">
          <h2 className="ns-title">
            {greeting()}, {me()?.name.split(" ")[0]}
          </h2>
          <div className="ns-source">
            <div className="ns-field">
              <span className="ns-field-label">Chat context</span>
              <SelectField
                aria-label="Chat context"
                className="w-full"
                value={pid}
                onValueChange={(value) => {
                  setPid(value);
                  if (!value) setRuntime(null);
                }}
                options={[
                  { value: "", label: "General", icon: <Ic n="layers" s={14} /> },
                  ...ps.map((p) => ({
                    value: p.id,
                    label: p.name,
                    icon: <PIcon p={p} s={14} />,
                  })),
                ]}
              />
            </div>
          </div>
        </div>
        <div className="ns-bottom">
          <Suggestions
            className="mb-3 justify-center"
            items={sugg.map(([i, s]) => ({
              key: s!,
              value: s!,
              content: (
                <>
                  <Ic n={i!} s={13} />
                  {s}
                </>
              ),
            }))}
            onSelect={(value) => start(value, agent)}
            disabled={unavailable}
          />
          <Composer
            key={q}
            placeholder={pid ? `Ask anything about ${ps.find((p) => p.id === pid)?.name ?? "this project"}` : "Ask Nova anything"}
            agent={agent}
            setAgent={setAgent}
            model={model}
            setModel={setModel}
            models={modelOptions}
            context={pid}
            contexts={[...ps.map((p): [string, string] => [p.id, p.name]), ["", "General"]]}
            setContext={(value) => {
              setPid(value);
              if (!value) setRuntime(null);
            }}
            mode={mode}
            setMode={setMode}
            modeOptions={WORK_MODES}
            runtime={pid && runtimeOptions?.fx_available ? runtime : undefined}
            setRuntime={pid && runtimeOptions?.fx_available ? setRuntime : undefined}
            disabled={unavailable}
            approval={approval}
            setApproval={setApproval}
            onSend={start}
            autoFocus={Boolean(q)}
            draftOnly={!liveChat}
            initial={q}
          />
          {unavailable && <p role="alert">Connect a compatible personal model in settings to use fx.</p>}
          {!liveChat && (
            <p className="ns-sample-note faint">
              Sample preview · <a href="/login">Sign in to work with Nova.</a>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- a new coding session ---------- */

export function NewSession({ issue0 }: { issue0: string | null }) {
  // Members can start Codes from tasks assigned to them. Owners and Admins can use the project board.
  const projects = useProjects().items.filter((p) => canSee(p) && p.status !== "complete");
  const ps = new Set(projects.map((p) => p.id));
  const [projectId, setProjectId] = useState("");
  const [branch, setBranch] = useState("");
  const { tasks } = useAllTasks();
  const mine = tasks.filter((t) => ps.has(t.project) && t.status !== "done" && t.type !== "epic" && (canManageIssues() || t.assignee === D().me));
  // A real workspace's tasks are known by key; the sample's by id.
  const [tid, setTid] = useState(issue0 ? (isLive() ? issue0 : (tasks.find((t) => t.key === issue0)?.id ?? "")) : "");
  const [note, setNote] = useState("");
  const [codingMode, setCodingMode] = useState<"plan" | "build">("build");
  const [menu, setMenu] = useState<string | null>(null);
  const [menuBtn, setMenuBtn] = useState(false);
  const [hl, setHl] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!note) {
      el.style.height = "";
      return;
    }
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [note]);
  const t = mine.find((issue) => issue.id === tid);
  const ws = wsId();
  const liveSession = isLive();
  const project = projects.find((item) => item.id === projectId);
  const pid = t?.project ?? (liveSession && project?.repo ? project.id : "");
  const scope = useMemo(() => (ws && pid ? { workspaceId: ws, projectId: pid } : undefined), [ws, pid]);
  const avail = useCodingAvailability(scope).data;
  const workspaceModels = useModels(liveSession ? ws : undefined).data;
  const [chosenModel, setChosenModel] = useState<string | null>(null);
  // On the platform, or on your own computer when one of yours runs `dotrix runner` for this project.
  const [where, setWhere] = useState<"cloud" | "local" | null>(null);
  const location = where ?? (avail && !avail.available && avail.local_available ? "local" : "cloud");
  // Kai codes on the model you pick here, your default model to start with. The engine that runs it follows from
  // the model (your preferred engine in Account → Your models, else the model's provider's own); on your own
  // computer, the tool signed in there decides.
  // The sample models demonstrate the control. A live project still supplies its coding allowlist.
  const draftModels = liveSession ? (workspaceModels ?? []).filter((item) => item.source === "personal").map((item) => item.id) : SAMPLE_COMPOSER_MODELS;
  const models = location === "cloud" ? (avail?.models ?? draftModels) : [];
  const model = location === "cloud" ? ((chosenModel && models.includes(chosenModel) ? chosenModel : avail?.default_model) ?? models[0] ?? null) : null;
  const ready = liveSession && (location === "local" ? avail?.local_available && (avail.local_tools ?? []).length > 0 : avail?.available && !!model);
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
  // How much goes through without waiting, as in Chat: your default to start, among the modes you may use.
  const approvals = APPROVAL_MODES.filter(([v]) => approvalModes().includes(v));
  const [approval, setApproval] = useState<ApprovalMode>(defaultApproval());
  const start = useStartCoding(scope, t?.key ?? "", approval, location, null, model, codingMode);
  // The issue list opens two ways: typing "@" or "/" (menu is the query) or the Issue button (menuBtn); the button never touches the note.
  const menuOpen = menu !== null || menuBtn;
  const found = !menuOpen ? [] : mine.filter((x) => `${x.key} ${x.title}`.toLowerCase().includes((menu ?? "").toLowerCase())).slice(0, 8);
  const go_ = () => {
    if (!pid || (!t && !note.trim()) || !ready || start.isPending) return;
    start.mutateAsync({ note: note.trim() || null, baseBranch: branch.trim() }).then(
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
    <div className="ns code-start">
      <div className="ns-mid">
        <Face c={CODING_AGENT.c} size={44} mood="idle" label={CODING_AGENT.name} />
        <h2 className="ns-title">Start a session</h2>
        {!t && (
          <div className="ns-source">
            <div className="ns-field">
              <span className="ns-field-label">Repository</span>
              <SelectField
                aria-label="Repository"
                placeholder="Choose a repository"
                value={projectId}
                onValueChange={(value) => {
                  setProjectId(value);
                  setBranch("");
                }}
                className="w-full"
                options={[
                  { value: "", label: "Choose a repository" },
                  ...projects.map((p) => ({
                    value: p.id,
                    label: p.repo ? `${p.repo} · ${p.name}` : `${p.name} · No repository`,
                  })),
                ]}
              />
            </div>
            {project?.repo && (
              <label>
                Starting branch
                <input className="input" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="Repository default" maxLength={200} />
              </label>
            )}
            {liveSession && project && !project.repo && !allowed("projects:manage") && <p className="faint">Ask a project admin to connect a repository.</p>}
            {liveSession && project && !project.repo && ws && allowed("projects:manage") && (
              <a
                className="btn btn-secondary"
                href={`/onboarding?${new URLSearchParams({ workspace: ws, project: project.id, mode: "project", step: "github" })}`}
              >
                <Ic n="github" s={16} /> Connect repository
              </a>
            )}
            {liveSession && !projects.length && allowed("projects:manage") && (
              <button type="button" className="btn btn-secondary" onClick={newProject}>
                New project
              </button>
            )}
          </div>
        )}
        <ChoiceCard
          label="Choose environment"
          choices={[
            ...(here || avail?.local_available || avail?.local_runner
              ? [
                  {
                    id: "local",
                    label: (hereRunner ? hereRunner.folder.split(/[\\/]/).filter(Boolean).pop() : null) ?? avail?.local_runner ?? "Your computer",
                    icon: <Ic n="laptop" s={16} />,
                    group: "This computer",
                    on: location === "local",
                    disabled: !here && !avail?.local_available,
                    note: avail?.local_available ? undefined : hereRunner?.state === "failed" ? "Stopped" : hereRunner ? "Starting…" : undefined,
                    tip:
                      hereRunner?.isolation === "sbx"
                        ? `In a Docker sandbox on this computer, on ${hereRunner.folder}: Kai may run commands there`
                        : (hereRunner?.folder ?? "In a worktree of your checkout, with the coding tool signed in there"),
                    onPick: () => setWhere("local"),
                  } satisfies Choice,
                ]
              : []),
            {
              id: "cloud",
              label: "Cloud sandbox",
              icon: <Ic n="cloud" s={16} />,
              group: "Cloud",
              on: location === "cloud",
              note: avail?.available === false ? "Off" : undefined,
              tip: avail?.reason ?? "In a sandbox on the platform",
              onPick: () => setWhere("cloud"),
            },
          ]}
          extra={
            here && slug && pkey
              ? (close) => (
                  <button
                    type="button"
                    className="cc-item"
                    disabled={adding || hereRunner?.state === "starting"}
                    onClick={() => {
                      codeHere();
                      setWhere("local");
                      close();
                    }}
                  >
                    <Ic n="folder-plus" s={16} />
                    <span className="trunc grow">{hereRunner ? "Choose another folder" : "Add a folder"}</span>
                  </button>
                )
              : undefined
          }
        />
        {liveSession && location === "local" && here && slug && pkey && !avail?.local_available && (
          <button type="button" className="btn btn-secondary" disabled={adding || hereRunner?.state === "starting"} onClick={codeHere}>
            <Ic n="folder-plus" s={16} /> {hereRunner ? "Choose another folder" : "Add a folder"}
          </button>
        )}
      </div>
      <div className="ns-bottom">
        <div className="dotrix-composer-wrap">
          <ChatComposer
            value={note}
            onSubmit={go_}
            header={
              t ? (
                <span className="cmp-chip" title={`${t.key} ${t.title}`}>
                  <Ic n="square-check" s={12} />
                  <span className="trunc">
                    {t.key} {t.title}
                  </span>
                  <ActionButton className="ibtn ibtn-xs" onClick={() => setTid("")} aria-label={`Remove ${t.key}`}>
                    <Ic n="x" s={11} />
                  </ActionButton>
                </span>
              ) : undefined
            }
            input={
              <textarea
                data-dotrix-control
                className="composer-textarea"
                ref={ref}
                rows={1}
                value={note}
                placeholder={t ? `What should Kai do on ${t.key}?` : "What should Kai do?"}
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
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    go_();
                  }
                }}
                aria-label="What should it do"
                aria-expanded={menuOpen}
                aria-controls="cs-issues"
              />
            }
            footerActions={
              <div className="cmp-footer-left">
                <CodingOptions mode={codingMode} setMode={setCodingMode} local={location === "local"} placement="above" focusInput={() => ref.current?.focus()}>
                  {(close) => (
                    <>
                      <div className="composer-menu-sep" />
                      <DesignButton
                        label="Pick an issue"
                        variant="ghost"
                        className="composer-menu-option"
                        icon={<Ic n="square-check" s={15} />}
                        onClick={() => {
                          close();
                          ask();
                        }}
                      />
                      {avail && (avail.local_available || location === "local" || here) && (
                        <>
                          <div className="composer-menu-sep" />
                          <WhereItCodes
                            location={location}
                            setWhere={setWhere}
                            cloudReady={avail.available}
                            cloudWhy={avail.reason}
                            localReady={avail.local_available}
                            localName={avail.local_runner}
                            localWhy={avail.local_reason}
                            folder={hereRunner}
                            canAdd={Boolean(here && slug && pkey)}
                            adding={adding}
                            onAdd={codeHere}
                            onClose={() => {
                              close();
                              ref.current?.focus();
                            }}
                          />
                        </>
                      )}
                    </>
                  )}
                </CodingOptions>
                <span className="cmp-status-badge accent" aria-label={`Coding mode: ${codingMode === "plan" ? "Plan" : "Build"}`} data-tip="Mode">
                  <Ic n={codingMode === "plan" ? "list-checks" : "hammer"} s={12} />
                  <span>{codingMode === "plan" ? "Plan" : "Build"}</span>
                </span>
                {approvals.length > 1 ? (
                  <ApprovalPick value={approval} onChange={setApproval} options={approvals} />
                ) : (
                  <span
                    className={`cmp-status-badge ${approval === "auto" ? "amber" : ""}`}
                    aria-label={`Approval mode: ${modeName(approval)}`}
                    data-tip="Approvals"
                  >
                    <Ic n="shield-check" s={12} />
                    <span>{modeName(approval)}</span>
                  </span>
                )}
                {!t && (
                  <button type="button" className="cmp-status-pill" onClick={ask} aria-label="Link an issue" data-tip="Pick an issue">
                    <Ic n="square-check" s={12} />
                    <span className="cmp-pill-label-compact">Issue</span>
                  </button>
                )}
              </div>
            }
            sendActions={
              <ComposerModel
                model={model}
                models={models.map((m): [string, string] => [m, modelName(m)])}
                onChange={setChosenModel}
                empty={location === "local" ? "Model managed locally" : "No models connected"}
              />
            }
            sendButton={
              <>
                <span
                  data-tip={
                    !liveSession
                      ? "Sign in to start coding"
                      : !pid
                        ? "Choose a repository or issue"
                        : !ready
                          ? ((location === "local" ? avail?.local_reason : avail?.reason) ?? "Kai can't code here yet")
                          : "Start coding"
                  }
                >
                  <button className="kt-send" onClick={go_} disabled={!pid || (!t && !note.trim()) || !ready || start.isPending} aria-label="Start coding">
                    <Ic n="arrow-up" s={15} />
                  </button>
                </span>
              </>
            }
          />
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
                className="pop cs-issue-pop"
                id="cs-issues"
                role="listbox"
                aria-label="Issues"
                style={{
                  position: "absolute",
                  bottom: "calc(100% + 8px)",
                  left: 0,
                  right: 0,
                  overflowY: "auto",
                  maxHeight: "min(320px, 40dvh)",
                  maxWidth: 520,
                  zIndex: 80,
                }}
              >
                <div className="composer-menu-heading">Link an issue</div>
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
                    {mine.length ? "No issue matches." : canManageIssues() ? "No open issues." : "No open issues are assigned to you."}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
        {!liveSession && (
          <p className="ns-sample-note faint">
            Sample preview · <a href="/login">Sign in</a> to start coding sessions.
          </p>
        )}
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
export function LineCounts({ files, onClick, tip }: { files: Record<string, unknown>[]; onClick?: () => void; tip?: string }) {
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

/** CI on the turn's commit: passed, or failed with Juno's look at the logs and "Ask Kai to fix" (a follow-up turn). */
function CiCard({ turn, scope, canFix, onFix }: { turn: CodingRun; scope: Scope | undefined; canFix: boolean; onFix: (message: string) => void }) {
  const [look] = useReviewRunQueries(scope, turn.ci_review_run_id ? [turn.ci_review_run_id] : []);
  const run = look?.data;
  const reply = run?.reply?.trim() ?? "";
  if (turn.ci_state === "passed") {
    return (
      <div className="row muted" style={{ gap: 6, fontSize: 12.5 }}>
        <Ic n="circle-check" s={13} />
        CI passed on {turn.commit_sha?.slice(0, 7)}
      </div>
    );
  }
  const fix = () =>
    onFix(
      `CI failed on PR #${turn.pr_number} at ${turn.commit_sha?.slice(0, 7)}. Fix it on this branch.` +
        (reply ? `\n\nJuno looked at the failed jobs' logs (its analysis, as evidence):\n\n${reply.slice(0, 4000)}` : ""),
    );
  return (
    <div className="change" role="group" aria-label="CI failed">
      <div className="change-h">
        <Ic n="circle-x" s={14} />
        <b style={{ fontWeight: 500 }}>CI failed on {turn.commit_sha?.slice(0, 7)}</b>
        <span className="sp" />
        {turn.ci_review_posted_url && (
          <a href={turn.ci_review_posted_url} target="_blank" rel="noreferrer" style={{ color: "var(--acc)", fontSize: 12 }}>
            On the PR
          </a>
        )}
      </div>
      <div className="change-b" style={{ fontSize: 13 }}>
        {!turn.ci_review_run_id ? (
          <span className="muted">Juno will look at the failed jobs.</span>
        ) : !run || run.status === "queued" || run.status === "running" ? (
          <span className="muted">Juno is reading the failed jobs' logs…</span>
        ) : reply ? (
          <Markdown>{reply}</Markdown>
        ) : (
          <span className="muted">Juno didn't say what failed; open the PR's checks.</span>
        )}
      </div>
      <div className="change-f">
        <span className="faint" style={{ fontSize: 12 }}>
          A follow-up turn on the same branch, approved like the first.
        </span>
        <span className="sp" />
        <ActionButton className="btn btn-sm btn-primary" disabled={!canFix} onClick={fix}>
          <Ic n="wrench" s={13} />
          Ask {CODING_AGENT.name} to fix
        </ActionButton>
      </div>
    </div>
  );
}

/** What a turn ended as when it used no tools: a refused or cut-off turn didn't work on anything. */
const NO_STEPS: Partial<Record<CodingRun["status"], string>> = {
  failed: "Failed before any steps",
  stopped: "Stopped before any steps",
  recovery_required: "Interrupted before any steps",
};

/** What a turn did, in a line, as Claude Code folds its tool calls: "Read 2 files, ran 2 commands, edited 3 files". */
function stepsSummary(events: CodingRun["events"], status?: CodingRun["status"]): string {
  let read = 0,
    edited = 0,
    ran = 0,
    other = 0;
  for (const e of events) {
    if (e.kind !== "tool") continue;
    if (/^Read\b/.test(e.text)) read++;
    else if (/^(Edited|Wrote|Created|Deleted)\b/.test(e.text)) edited++;
    else if (/^Ran\b/.test(e.text)) ran++;
    else other++;
  }
  const parts = [
    read && `read ${read} file${read > 1 ? "s" : ""}`,
    ran && `ran ${ran} command${ran > 1 ? "s" : ""}`,
    edited && `edited ${edited} file${edited > 1 ? "s" : ""}`,
    other && `used ${other} other tool${other > 1 ? "s" : ""}`,
  ].filter(Boolean) as string[];
  const line = parts.join(", ");
  if (line) return line[0]!.toUpperCase() + line.slice(1);
  return (status && NO_STEPS[status]) ?? "Worked on it";
}

export function copyText(text: string) {
  void navigator.clipboard
    ?.writeText(text)
    .then(() => toast("Copied"))
    .catch(() => toast("It couldn't be copied"));
}

/** One of Kai's turns: your request on the right; then what it did folded into one line (open it for each step),
 *  its summary, and a row with copy, the time, and its changes. */
function KaiTurn({
  turn,
  issueTitle,
  busy,
  revert,
  onPath,
  onChanges,
  onShot,
  shotSrc,
}: {
  turn: CodingRun;
  issueTitle: string;
  busy: boolean;
  revert: ReturnType<typeof useRevertCoding>;
  onPath: (path: string, turnId?: string) => void;
  onChanges: (turnId: string) => void;
  onShot: (src: string, name: string) => void;
  shotSrc: (runId: string, index: number) => string;
}) {
  // output: under its command; background tasks: listed on their own (KaiBackground)
  const steps = turn.events.filter((e) => e.kind !== "text" && !e.kind.startsWith("output") && !e.kind.startsWith("background-"));
  const liveText = !turn.summary ? turn.events.filter((e) => e.kind === "text" && e.text.trim()).at(-1)?.text : undefined;
  const replyText = turn.summary || liveText;
  const working = turn.status === "running";
  const asked = turn.note || `Work on ${turn.issue_key}${issueTitle ? `: ${issueTitle}` : ""}`;
  const mine = turn.requested_by_id === D().me;
  const added = turn.files_changed.reduce((n, f) => n + Number(f.added ?? 0), 0);
  const removed = turn.files_changed.reduce((n, f) => n + Number(f.removed ?? 0), 0);
  return (
    <div className="kt">
      <ChatMessage
        side="outgoing"
        footer={
          <div className="chat-ask-meta">
            {!mine && <span>{who(turn.requested_by_id ?? "")?.name ?? "Someone"} ·</span>}
            <span>{ago(ms(turn.created_at))}</span>
            <ActionButton className="ibtn ibtn-xs" onClick={() => copyText(asked)} aria-label="Copy the request" data-tip="Copy">
              <Ic n="copy" s={13} />
            </ActionButton>
          </div>
        }
      >
        {asked}
      </ChatMessage>
      {(steps.length > 0 || replyText || turn.error) && (
        <ChatTranscriptReply
          avatar={<Av id={CODING_AGENT.id} cls="sm" tip={false} />}
          author={CODING_AGENT.name}
          bubbleProps={{ className: "md kt-markdown" }}
          beforeBody={
            steps.length > 0 ? (
              <Trace className="agent-trace kt-trace">
                <TraceCollapsible>
                  <TraceCollapsibleTrigger>
                    <TraceLine status={working ? "running" : undefined}>
                      <TraceIcon>{working ? <Ic n="spinner-gap" cls="animate-spin" /> : <Ic n="list-checks" />}</TraceIcon>
                      <TraceTitle>{working ? (steps.at(-1)?.text ?? "Working") : stepsSummary(turn.events, turn.status)}</TraceTitle>
                    </TraceLine>
                  </TraceCollapsibleTrigger>
                  <TraceCollapsibleContent>
                    <ToolCalls
                      events={turn.events.slice(-200)}
                      running={working}
                      onPath={(path) => onPath(path, turn.id)}
                      known={turn.files_changed.map(fileOf)}
                      render={(text) => <PathLinks text={text} paths={turn.files_changed.map(fileOf)} onPath={(path) => onPath(path, turn.id)} />}
                    />
                  </TraceCollapsibleContent>
                </TraceCollapsible>
              </Trace>
            ) : undefined
          }
          body={
            replyText ? (
              <Markdown
                onCode={(code) =>
                  turn.files_changed.some((f) => fileOf(f) === code.replace(/:\d+$/, "")) ? () => onPath(code.replace(/:\d+$/, ""), turn.id) : undefined
                }
              >
                {replyText}
              </Markdown>
            ) : undefined
          }
        >
          {turn.error && <div className="kt-error">{turn.error}</div>}
          {(turn.screenshots ?? []).length > 0 && (
            <div className="cs-shots" aria-label="Screenshots from the browser">
              {(turn.screenshots ?? []).map((sh) => {
                const src = shotSrc(turn.id, sh.index);
                return (
                  <button key={sh.index} className="cs-shot" onClick={() => onShot(src, sh.name)} aria-label={`Open the screenshot ${sh.name}`}>
                    <img src={src} alt={`Screenshot: ${sh.name}`} loading="lazy" />
                    <span className="faint trunc">{sh.name}</span>
                  </button>
                );
              })}
            </div>
          )}
          <div className="kt-actions">
            {turn.summary && (
              <ActionButton className="ibtn ibtn-xs" onClick={() => copyText(turn.summary ?? "")} aria-label="Copy Kai's reply" data-tip="Copy">
                <Ic n="copy" s={13} />
              </ActionButton>
            )}
            {turn.finished_at && <span className="faint">{ago(ms(turn.finished_at))}</span>}
            {mine && (
              <ContextUsage
                usage={{ input: turn.input_tokens, output: turn.output_tokens, cost: turn.cost_usd, model: turn.model ? modelName(turn.model) : null }}
              />
            )}
            {turn.files_changed.length > 0 && (
              <button className="kt-lines" onClick={() => onChanges(turn.id)} data-tip="Open these changes">
                <Ic n="git-compare" s={12} />
                {turn.files_changed.length} file{turn.files_changed.length > 1 ? "s" : ""}
                <span className="plus">+{added}</span>
                <span className="minus">−{removed}</span>
              </button>
            )}
          </div>
        </ChatTranscriptReply>
      )}
      {turn.commit_sha && (
        <Checkpoint
          label={
            <span>
              {turn.revert_of ? "Reverted" : `Turn ${turn.turn}`} · <span className="mono">{turn.commit_sha.slice(0, 7)}</span>
              {turn.branch ? <span className="faint"> on {turn.branch}</span> : null}
            </span>
          }
        >
          {turn.can_revert && !busy && (
            <button className="kt-lines" disabled={revert.isPending} onClick={() => revert.mutate(turn.id)}>
              <Ic n="undo-2" s={12} />
              Revert this turn
            </button>
          )}
        </Checkpoint>
      )}
    </div>
  );
}

/** The panes a session can show beside it; the address keeps the open ones (`panel=changes,files`). */
const paneList = (value: string | null, PANES: typeof CODING_VIEWS): CodingPaneId[] =>
  (value ?? "")
    .split(",")
    .map((v) => (v === "coding" ? "changes" : v))
    .filter((v): v is CodingPaneId => /^(changes|files|terminal|review|browser)$|^(terminal|browser)-[1-9]\d{0,5}$/.test(v))
    .filter((v) => PANES.some((p) => p.id === codingPaneType(v)))
    .filter((v, i, all) => all.indexOf(v) === i);

export function Session({ cs }: { cs: CodingSession }) {
  const ws = wsId();
  const scope = useMemo(() => (ws ? { workspaceId: ws, projectId: cs.project_id } : undefined), [ws, cs.project_id]);
  const turnsQuery = useCodingSession(scope, cs.session_id);
  const turns = turnsQuery.data ?? [];
  const latest = turns.at(-1);
  const [codingMode, setCodingMode] = useState<"plan" | "build">("build");
  // The open session is followed as it happens; its turns land in the query above.
  useCodingSessionStream(scope, cs.session_id, turns.some(isOpenTurn));
  const decide = useDecideCoding(scope, cs.issue_key);
  const stop = useStopCoding(scope, cs.issue_key);
  const recover = useRecoverCoding(scope, cs.issue_key);
  const revert = useRevertCoding(scope, cs.issue_key, defaultApproval());
  const follow = useFollowUp(scope, cs.session_id, cs.issue_key, defaultApproval());
  // While Kai works, a message steers the turn (when it can take one) or waits as the next turn, as in Claude Code.
  const codingInputs = useCodingInputs(scope, cs.session_id).data ?? [];
  const sendInput = useSendCodingInput(scope, cs.session_id);
  const cancelInput = useCancelCodingInput(scope, cs.session_id);
  const [pickedKind, setPickedKind] = useState<"steer" | "queue" | null>(null);
  const retryInput = useRef<{ signature: string; client_id: string } | null>(null);
  const search = useRoute().search;
  // The open panes: the address's (`panel=`, Files for a `file=` link), else the ones last open in this browser.
  const [lastPanes, setLastPanes] = useStoredText("dotrix.coding.panes", "");
  const asked = search.get("panel");
  // Browser is a pane only in the desktop app, and only while it's on there (Settings → Browser).
  const browserOff = useBrowserSettings()?.enabled === false;
  const PANES = useMemo(() => CODING_VIEWS.filter((view) => view.id !== "browser" || !browserOff), [browserOff]);
  const panes = paneList(asked ?? (search.has("file") ? "files" : lastPanes), PANES);
  const setPanes = (next: CodingPaneId[], extra: Record<string, string> = {}) => {
    const query = new URLSearchParams(search);
    // Opening a file or a turn sets them; closing the last pane lets them go.
    for (const key of !next.length || Object.keys(extra).length ? ["panel", "file", "line", "turn", "ref"] : ["panel"]) query.delete(key);
    if (next.length) query.set("panel", next.join(","));
    for (const [key, value] of Object.entries(extra)) query.set(key, value);
    go("codes", {}, { search: query.toString(), replace: true });
    setLastPanes(next.join(","));
  };
  const [activePane, setActivePane] = useActivePane(panes);
  const openPane = (view: CodingView, extra: Record<string, string> = {}) => {
    setActivePane(view);
    setPanes(panes.includes(view) ? panes : [...panes, view], extra);
  };
  const addPane = (view: CodingView) => {
    const id = newCodingPane(view, panes);
    setActivePane(id);
    if (!panes.includes(id)) setPanes([...panes, id]);
  };
  const closePane = (view: CodingPaneId) => setPanes(panes.filter((v) => v !== view));
  const togglePane = (view: CodingView) => (panes.includes(view) ? closePane(view) : openPane(view));
  // The address always says which panes are open (the list beside the session folds for them: screens/Coding.tsx).
  useEffect(() => {
    if (panes.length && !search.has("panel")) setPanes(panes);
  });
  // The session's details (environment, background tasks, PR, outputs, usage): a popover anchored under its button across viewports.
  const [detailsPop, setDetailsPop] = useState(false);
  const toggleDetails = () => setDetailsPop((open) => !open);
  /** A file the session changed, opened in Files (in the latest turn that changed it, or the latest). */
  const openPath = (path: string, turnId?: string) => {
    const owner = turnId ?? [...turns].reverse().find((t) => t.files_changed.some((f) => fileOf(f) === path))?.id ?? latest?.id;
    setDetailsPop(false);
    openPane("files", { file: path, ...(owner ? { turn: owner } : {}) });
  };
  const openChanges = (turnId?: string) => {
    setDetailsPop(false);
    openPane("changes", turnId ? { turn: turnId } : {});
  };
  // In the desktop app, Kai asking for its browser tab in this session opens the Browser pane (components/BrowserPane.tsx makes the tab).
  const showBrowser = useRef(openPane);
  showBrowser.current = openPane;
  useEffect(() => desktopBrowser()?.onKai((request) => request.sessionId === cs.session_id && showBrowser.current("browser")), [cs.session_id]);
  // Claude Code's shortcuts: ⌘/Ctrl+\ closes the panes, ⌘/Ctrl+Shift+D the changes, Ctrl+` the terminal.
  const keys = useRef({ panes, togglePane, setPanes });
  keys.current = { panes, togglePane, setPanes };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === "\\" && keys.current.panes.length) {
        e.preventDefault();
        keys.current.setPanes([]);
      } else if (mod && e.shiftKey && e.key.toLowerCase() === "d") {
        e.preventDefault();
        keys.current.togglePane("changes");
      } else if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        keys.current.togglePane("terminal");
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  const t = isLive() ? { id: cs.issue_key, key: cs.issue_key } : D().tasks.find((x) => x.key === cs.issue_key);
  // People see Kai; the engine underneath (cs.agent) stays on the run and in the logs.
  const kai = CODING_AGENT.name;
  const [ask, setAsk] = useState("");
  const [label0, c] = STATUS[cs.status];
  const label = latest ? statusLabel(latest) : label0;
  const busy = BUSY.includes(cs.status) || cs.state === "closed";
  // Kai is on a turn (or one waits): what you type goes to it, steering or queued, rather than as a follow-up.
  const working = cs.state !== "closed" && Boolean(latest) && BUSY.includes(latest!.status);
  const steerable = Boolean(latest?.accepts_steering);
  const inputKind: "steer" | "queue" = steerable ? (pickedKind ?? "steer") : "queue";
  // The latest turn that reached the PR: CI runs on its commit.
  const pushed = [...turns].reverse().find((t) => t.commit_sha && t.pr_number);
  // A screenshot opened large over everything; Escape or a click closes it.
  const [shot, setShot] = useState<{ src: string; name: string } | null>(null);
  // The title's menu and the panes menu (the "…"), closed by a click elsewhere or Escape.
  const [menu, setMenu] = useState<null | "title" | "panes">(null);
  useEffect(() => {
    if (!shot && !menu && !detailsPop) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (shot) return;
      setMenu(null);
      setDetailsPop(false);
    };
    const away = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (menu && !target.closest(".cs-menu, [data-menu]")) setMenu(null);
      if (detailsPop && !target.closest(".cs-details-pop, [data-details]")) setDetailsPop(false);
    };
    document.addEventListener("keydown", esc);
    document.addEventListener("mousedown", away);
    return () => {
      document.removeEventListener("keydown", esc);
      document.removeEventListener("mousedown", away);
    };
  }, [shot, menu, detailsPop]);
  useEffect(() => {
    setMenu(null);
    setDetailsPop(false);
  }, [cs.session_id]);
  const send = () => {
    const message = ask.trim();
    if (!message) return;
    if (working) {
      // The same message sent again (a retry) keeps its id, so it's sent once.
      const signature = JSON.stringify([cs.session_id, message, inputKind, codingMode]);
      const retry = retryInput.current;
      const client_id = retry?.signature === signature ? retry.client_id : crypto.randomUUID();
      retryInput.current = { signature, client_id };
      sendInput.mutate(
        { client_id, kind: inputKind, message, work_mode: codingMode, approval_mode: latest?.approval_mode ?? null },
        {
          onSuccess: (sent) => {
            retryInput.current = null;
            // The turn had just finished: this is a follow-up after all.
            if (!sent) follow.mutate({ message, work_mode: codingMode });
          },
        },
      );
      setAsk("");
      return;
    }
    if (busy) return;
    follow.mutate({ message, work_mode: codingMode });
    setAsk("");
  };
  const box = useRef<HTMLTextAreaElement>(null);
  // The message box grows with what's typed, up to about eight lines.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    if (!ask) {
      el.style.height = "";
      return;
    }
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [ask]);
  const shotSrc = (runId: string, index: number) => `/v1/workspaces/${ws}/projects/${cs.project_id}/coding/runs/${runId}/screenshots/${index}`;
  const details = (
    <SessionDetails
      scope={scope}
      cs={cs}
      turns={turns}
      onOpenFile={openPath}
      onOpenChanges={openChanges}
      onShot={(src, name) => setShot({ src, name })}
      shotSrc={shotSrc}
      onClose={() => setDetailsPop(false)}
      onRefresh={() => void turnsQuery.refetch()}
      refreshing={turnsQuery.isFetching}
    />
  );
  const detailsOn = detailsPop;
  return (
    <div className="conv">
      <div className="conv-main">
        <SessionHeader>
          <ActionButton className="ibtn ibtn-sm cs-back" onClick={() => openCoding("")} aria-label="Back to sessions" data-tip="Sessions">
            <Ic n="arrow-left" s={15} />
          </ActionButton>
          <div className="cs-title-wrap">
            <button
              className={`cs-title ${menu === "title" ? "on" : ""}`}
              data-menu
              onClick={() => setMenu(menu === "title" ? null : "title")}
              aria-haspopup="menu"
              aria-expanded={menu === "title"}
            >
              <span className="trunc">{cs.title ?? cs.issue_title}</span>
              <Ic n="chevron-down" s={14} />
            </button>
            {menu === "title" && (
              <div className="pop cs-menu" role="menu" aria-label="Session">
                {t && cs.issue_key && (
                  <button role="menuitem" onClick={() => (setMenu(null), openTask(t.id))}>
                    <Ic n="circle-dot" s={14} />
                    Open {cs.issue_key}
                  </button>
                )}
                {cs.thread_id && (
                  <button role="menuitem" onClick={() => (setMenu(null), open(`thread=${cs.thread_id}&project=${cs.project_key}`))}>
                    <Ic n="message-square" s={14} />
                    Open the conversation it came from
                  </button>
                )}
                {cs.pr_url && (
                  <a role="menuitem" href={cs.pr_url} target="_blank" rel="noreferrer" onClick={() => setMenu(null)}>
                    <Ic n="git-pull-request" s={14} />
                    Open pull request #{cs.pr_number}
                  </a>
                )}
                <button role="menuitem" onClick={() => (setMenu(null), copyText(location.href))}>
                  <Ic n="link" s={14} />
                  Copy a link to this session
                </button>
              </div>
            )}
          </div>
          <span className={`badge ${c}`}>{label}</span>
          {cs.thread_id && (
            // Started from a conversation: its outcome goes back there (it stays private to whoever started it).
            <span className="cs-from" data-tip="Started from a conversation">
              <Ic n="message-square" s={13} />
            </span>
          )}
          <span className="sp" />
          {(latest?.files_changed?.length ?? 0) > 0 && latest && (
            <LineCounts files={latest.files_changed} onClick={() => openChanges(latest.id)} tip="Open changes" />
          )}
          {pushed?.ci_state && (
            <button
              className={`pillbtn cs-ci-pill ${pushed.ci_state}`}
              onClick={() => openPane(pushed.ci_state === "failed" ? "review" : "terminal")}
              data-tip={`CI ${pushed.ci_state}`}
              aria-label={`CI ${pushed.ci_state}`}
            >
              <Ic n={pushed.ci_state === "passed" ? "circle-check" : "circle-x"} s={12} />
              CI
            </button>
          )}
          <button
            className={`cs-view ${detailsOn ? "on" : ""}`}
            data-details
            onClick={toggleDetails}
            aria-pressed={detailsOn}
            aria-label="Session details"
            data-tip={detailsOn ? undefined : "Details"}
          >
            <Ic n="list-bullets" s={16} />
          </button>
          {/* Last in the bar, where the session meets the panes: shows them (Changes first) or hides them all. */}
          <button
            className={`cs-view cs-pane-toggle ${panes.length ? "on" : ""}`}
            onClick={() => {
              setPanes(panes.length ? [] : ["changes"]);
              setMenu(null);
            }}
            aria-pressed={panes.length > 0}
            aria-label={panes.length ? "Hide the panes" : "Show the panes"}
            data-tip={panes.length ? "Hide panes" : "Show panes"}
          >
            <Ic n="panel-right" s={16} />
          </button>
        </SessionHeader>
        {shot && (
          <Lightbox
            isOpen
            hasZoom
            onOpenChange={(open) => {
              if (!open) setShot(null);
            }}
            media={{ src: shot.src, alt: `Screenshot: ${shot.name}`, caption: shot.name }}
          />
        )}
        {detailsPop && (
          <div className="pop cs-details-pop" role="dialog" aria-label="Session details">
            {details}
          </div>
        )}
        <ChatLayout
          className="dotrix-chat-layout"
          density={S.prefs.density === "compact" ? "compact" : "balanced"}
          composer={
            <div className="chat-input kt-input dotrix-composer-wrap">
              {latest && <KaiBackground run={latest} kai={kai} />}
              {working && (
                <div className="chat-delivery-row">
                  <label htmlFor="coding-delivery-kind">Send as</label>
                  <SelectField
                    id="coding-delivery-kind"
                    size="sm"
                    className="chat-delivery-select"
                    aria-label="Delivery action"
                    value={inputKind}
                    onValueChange={(value) => setPickedKind(value as "steer" | "queue")}
                    options={[...(steerable ? [{ value: "steer", label: "Steer this turn" }] : []), { value: "queue", label: "Queue for the next turn" }]}
                  />
                </div>
              )}
              <Queue
                entries={codingInputs
                  .filter(
                    (item) =>
                      item.status === "pending" ||
                      item.status === "sending" ||
                      item.status === "rejected" ||
                      (item.status === "accepted" && item.run_id === latest?.id),
                  )
                  .slice(0, 20)
                  .reverse()
                  .map((item) => ({
                    id: item.id,
                    kind: item.kind,
                    message: item.message,
                    status: item.status,
                    error: item.note,
                    said:
                      item.status === "accepted"
                        ? `${kai} has it`
                        : item.status === "rejected"
                          ? "Not delivered"
                          : item.status === "sending"
                            ? "Sending…"
                            : item.kind === "steer"
                              ? `Waiting for ${kai}'s next step`
                              : "Waiting for this turn to end",
                    onCancel: item.status === "pending" ? () => cancelInput.mutate(item.id) : undefined,
                    cancelling: cancelInput.isPending,
                  }))}
              />
              <ChatComposer
                value={ask}
                isDisabled={busy && !working}
                isStopShown={Boolean(latest?.can_stop && (latest.status === "running" || latest.status === "queued") && !ask.trim())}
                onSubmit={send}
                footerActions={
                  <div className="cmp-footer-left">
                    <CodingOptions
                      mode={codingMode}
                      setMode={setCodingMode}
                      local={latest?.location === "local"}
                      disabled={busy && !(working && inputKind === "queue")}
                      placement="above"
                      focusInput={() => box.current?.focus()}
                    />
                    <span className="cmp-status-badge accent" aria-label={`Coding mode: ${codingMode === "plan" ? "Plan" : "Build"}`} data-tip="Mode">
                      <Ic n={codingMode === "plan" ? "list-checks" : "hammer"} s={12} />
                      <span>{codingMode === "plan" ? "Plan" : "Build"}</span>
                    </span>
                    {latest?.approval_mode && (
                      <span
                        className={`cmp-status-badge ${latest.approval_mode === "auto" ? "amber" : ""}`}
                        aria-label={`Approval mode: ${modeName(latest.approval_mode)}`}
                        data-tip="Approvals"
                      >
                        <Ic n="shield-check" s={12} />
                        <span>{modeName(latest.approval_mode)}</span>
                      </span>
                    )}
                  </div>
                }
                input={
                  <textarea
                    data-dotrix-control
                    className="composer-textarea"
                    ref={box}
                    rows={1}
                    placeholder={
                      cs.state === "closed"
                        ? "This session is closed"
                        : working && inputKind === "steer"
                          ? `Tell ${kai} something while it works`
                          : working
                            ? `Queue a message for ${kai}'s next turn`
                            : (latest?.questions ?? []).length
                              ? `Answer ${kai}'s questions`
                              : `Ask ${kai} for a follow-up on the same branch`
                    }
                    value={ask}
                    disabled={busy && !working}
                    onChange={(e) => setAsk(e.target.value)}
                    aria-label="Follow-up"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                        e.preventDefault();
                        send();
                      }
                    }}
                  />
                }
                sendActions={<ComposerModel model={latest?.model} empty={cs.location === "local" ? "Model managed locally" : "Model not recorded"} />}
                sendButton={
                  <>
                    {latest?.can_stop && (latest.status === "running" || latest.status === "queued") && !ask.trim() ? (
                      <ChatSendButton isStopShown isDisabled={stop.isPending} onStop={() => stop.mutate(latest.id)} aria-label="Stop coding turn" />
                    ) : (
                      <ChatSendButton
                        status={sendInput.isPending || follow.isPending ? "sending" : busy && !working ? "waiting" : "ready"}
                        isDisabled={(busy && !working) || !ask.trim() || follow.isPending || sendInput.isPending}
                        onSend={send}
                      />
                    )}
                  </>
                }
              />
              <div className="kt-foot">
                <span className="sp" />
                {cs.location !== "local" && cs.sandbox && (
                  <span
                    className={`sd-state ${cs.sandbox}`}
                    data-tip={
                      cs.sandbox === "warm"
                        ? "Sandbox ready"
                        : cs.sandbox === "asleep"
                          ? "Sandbox asleep: it wakes on the next turn"
                          : "No sandbox: the next turn starts one"
                    }
                    aria-label={`Sandbox ${cs.sandbox}`}
                  />
                )}
              </div>
            </div>
          }
        >
          <ChatMessageList followKey={latest?.id ?? cs.session_id}>
            <div className="chat-col kt-col">
              {turns.map((turn) => (
                <Fragment key={turn.id}>
                  <KaiTurn
                    turn={turn}
                    issueTitle={cs.issue_title}
                    busy={busy}
                    revert={revert}
                    onPath={openPath}
                    onChanges={openChanges}
                    onShot={(src, name) => setShot({ src, name })}
                    shotSrc={shotSrc}
                  />
                  <BackgroundTasks scope={scope} run={turn} />
                </Fragment>
              ))}
              {!busy && latest && (latest.questions ?? []).length > 0 && (
                <div className="change" aria-label={`${kai}'s questions`}>
                  <div className="change-h">
                    <Ic n="question" s={14} />
                    <b style={{ fontWeight: 500 }}>{kai} has questions</b>
                  </div>
                  <div className="change-b">
                    <ol className="cs-plan-list">
                      {(latest.questions ?? []).map((question, index) => (
                        <li key={index}>{question}</li>
                      ))}
                    </ol>
                  </div>
                  <div className="change-f">
                    <span className="faint" style={{ fontSize: 12 }}>
                      Answer below: your reply is the next turn. Anything queued waits until then.
                    </span>
                    <span className="sp" />
                    <ActionButton className="btn btn-sm btn-primary" onClick={() => box.current?.focus()}>
                      Answer
                    </ActionButton>
                  </div>
                </div>
              )}
              {latest?.plan_result &&
                (() => {
                  const planTasks = Array.isArray(latest.plan_result.tasks) ? latest.plan_result.tasks : [];
                  const planCriteria = Array.isArray(latest.plan_result.acceptance_criteria) ? latest.plan_result.acceptance_criteria.map(String) : [];
                  const planQuestions = Array.isArray(latest.plan_result.open_questions) ? latest.plan_result.open_questions.map(String) : [];
                  return (
                    <div className="change" aria-label="Kai's saved plan">
                      <div className="change-h">
                        <Ic n="list-checks" s={14} />
                        <b style={{ fontWeight: 500 }}>{String(latest.plan_result.title ?? "Implementation plan")}</b>
                        <span className="badge">Saved plan</span>
                      </div>
                      <div className="agent-plan-body">
                        {Boolean(latest.plan_result.summary) && <p style={{ margin: 0 }}>{String(latest.plan_result.summary)}</p>}
                        <PlanSteps
                          title={`${planTasks.length} task${planTasks.length === 1 ? "" : "s"}`}
                          steps={planTasks.map((planTask) => ({
                            title: String(planTask.title ?? ""),
                            detail: planTask.detail ? String(planTask.detail) : undefined,
                            note: Array.isArray(planTask.depends_on) && planTask.depends_on.length ? `after ${planTask.depends_on.join(", ")}` : undefined,
                          }))}
                        />
                        <TraceList title="Acceptance criteria" items={planCriteria} icon="check-square" />
                        <TraceList title="Open questions" items={planQuestions} icon="question" />
                      </div>
                      <div className="change-f">
                        <span className="faint" style={{ fontSize: 12 }}>
                          Build all at once, or one task per turn.
                        </span>
                        <span className="sp" />
                        {planTasks.length > 1 && (
                          <ActionButton
                            className="btn btn-sm btn-secondary"
                            disabled={busy || follow.isPending}
                            title="A turn for each task, in order: the next starts when one finishes, and you can cancel what's left"
                            onClick={() =>
                              follow.mutate({
                                message: "Build the selected plan, one task at a time",
                                work_mode: "build",
                                source_plan_id: latest.id,
                                step_by_step: true,
                              })
                            }
                          >
                            Build step by step
                          </ActionButton>
                        )}
                        <ActionButton
                          className="btn btn-sm btn-primary"
                          disabled={busy || follow.isPending}
                          onClick={() =>
                            follow.mutate({
                              message: "Build the selected plan",
                              work_mode: "build",
                              source_plan_id: latest.id,
                            })
                          }
                        >
                          <Ic n="hammer" s={12} />
                          Build this plan
                        </ActionButton>
                      </div>
                    </div>
                  );
                })()}
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
                        <ActionButton
                          className="btn btn-sm btn-secondary"
                          disabled={decide.isPending}
                          onClick={() => decide.mutate({ runId: latest.id, decision: "reject" })}
                        >
                          Reject
                        </ActionButton>
                        <ActionButton
                          className="btn btn-sm btn-primary"
                          disabled={decide.isPending}
                          onClick={() => decide.mutate({ runId: latest.id, decision: "approve" })}
                        >
                          <Ic n="check" s={13} />
                          Approve
                        </ActionButton>
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
                    <span className="sp" />
                    <LineCounts files={latest.files_changed} onClick={() => openChanges(latest.id)} tip="Open the changes" />
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
                  {(latest.ci_sensitive ?? []).length > 0 && <CiSensitiveNote files={latest.ci_sensitive ?? []} />}
                  <div className="change-f">
                    <span className="faint" style={{ fontSize: 12 }}>
                      Accepted, they're pushed to {latest.branch ? <InlineCode>{latest.branch}</InlineCode> : "a new branch"} and the pull request is opened or
                      updated.
                    </span>
                    <span className="sp" />
                    {latest.can_stop && !latest.can_decide && (
                      <ActionButton className="btn btn-sm btn-secondary" disabled={stop.isPending} onClick={() => stop.mutate(latest.id)}>
                        Discard
                      </ActionButton>
                    )}
                    {latest.can_decide && (
                      <>
                        <ActionButton
                          className="btn btn-sm btn-secondary"
                          disabled={decide.isPending}
                          onClick={() => decide.mutate({ runId: latest.id, decision: "reject" })}
                        >
                          Discard
                        </ActionButton>
                        <ActionButton
                          className="btn btn-sm btn-primary"
                          disabled={decide.isPending}
                          onClick={() => decide.mutate({ runId: latest.id, decision: "approve" })}
                        >
                          <Ic n="check" s={13} />
                          Accept and push
                        </ActionButton>
                      </>
                    )}
                  </div>
                </div>
              )}
              {pushed?.ci_state && <CiCard turn={pushed} scope={scope} canFix={!busy && !follow.isPending} onFix={(message) => follow.mutate(message)} />}
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
                        <ActionButton
                          className="btn btn-sm btn-secondary"
                          disabled={recover.isPending}
                          onClick={() => recover.mutate({ runId: latest.id, action: "discard" })}
                        >
                          Discard
                        </ActionButton>
                        <ActionButton
                          className="btn btn-sm btn-primary"
                          disabled={recover.isPending}
                          onClick={() => recover.mutate({ runId: latest.id, action: "check" })}
                        >
                          <Ic n="refresh-cw" s={12} />
                          Check and recover
                        </ActionButton>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          </ChatMessageList>
        </ChatLayout>
      </div>
      {panes.length > 0 && (
        <CodingPanes
          scope={scope}
          cs={cs}
          active={activePane}
          views={panes}
          items={PANES}
          onAdd={addPane}
          onSelect={setActivePane}
          onOpen={openPane}
          onClose={closePane}
          onCloseAll={() => setPanes([])}
          onAskFix={setAsk}
          fixLabel={`Ask ${CODING_AGENT.name} to fix`}
        />
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
  <>
    <SessionHeader />
    {loading ? (
      <div className="chat-scroll">
        <div className="chat-col">
          <p className="muted" aria-hidden="true">
            {text}
          </p>
          <ChatLoadingState label={text} />
        </div>
      </div>
    ) : (
      <div className="chat-scroll" style={{ display: "flex" }}>
        <div className="chat-pending">
          <span>{text}</span>
          {onRetry && (
            <ActionButton className="btn btn-secondary btn-sm" onClick={onRetry}>
              Try again
            </ActionButton>
          )}
          {inbox && (
            <ActionButton className="btn btn-secondary btn-sm" onClick={() => go("inbox", {}, { search: "tab=needs" })}>
              Open Inbox
            </ActionButton>
          )}
          <ActionButton className="btn btn-ghost btn-sm" onClick={back[1]}>
            {back[0]}
          </ActionButton>
        </div>
      </div>
    )}
  </>
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

function DemoConversation({ id }: { id: string }) {
  const thread = D().threads.find((item) => item.id === id);
  const [mode, setMode] = useState<WorkMode>("discuss");
  const [approval, setApproval] = useState<ApprovalMode>(defaultApproval());
  const modelOptions = useMemo(
    () =>
      [...(thread?.model && !SAMPLE_COMPOSER_MODELS.includes(thread.model) ? [thread.model] : []), ...SAMPLE_COMPOSER_MODELS].map((item): [string, string] => [
        item,
        modelName(item),
      ]),
    [thread?.model],
  );
  const [chosenModel, setModel] = useState<string>(thread?.model ?? SAMPLE_COMPOSER_MODELS[0] ?? "");
  if (!thread) return <Pending text="This sample conversation is no longer available." />;
  const p = proj(thread.project ?? "");
  return (
    <div className="conv">
      <div className="conv-main">
        <SessionHeader>
          <ActionButton className="ibtn ibtn-sm cs-back" onClick={() => open("")} aria-label="Back to conversations">
            <Ic n="arrow-left" s={15} />
          </ActionButton>
          <b className="trunc" style={{ fontWeight: 600, fontSize: 13.5 }}>
            {thread.title}
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
              General
            </span>
          )}
        </SessionHeader>
        <ChatLayout
          className="dotrix-chat-layout"
          density={S.prefs.density === "compact" ? "compact" : "balanced"}
          composer={
            <div className="chat-input">
              <Composer
                placeholder="Draft a reply"
                agent="auto"
                model={chosenModel}
                setModel={setModel}
                models={modelOptions}
                context={p?.name ?? "General"}
                mode={mode}
                setMode={setMode}
                modeOptions={WORK_MODES}
                approval={approval}
                setApproval={setApproval}
                onSend={() => {}}
                draftOnly
              />
            </div>
          }
        >
          <ChatMessageList>
            <div className="chat-col">
              <p className="muted">
                Sample conversation · <a href="/login">Sign in to work with Nova.</a>
              </p>
              {thread.messages.map((message) => (
                <Message key={message.id} m={message} projectId={thread.project}>
                  {message.changes?.map((change) => (
                    <ChangeCard key={change.id} ch={change} />
                  ))}
                  {message.limit && (
                    <LimitNotice
                      said={`${message.limit.provider}: rate limit reached`}
                      resetsAt={message.limit.resetsAt}
                      onContinue={() => toast("Sign in to continue conversations")}
                    />
                  )}
                </Message>
              ))}
            </div>
          </ChatMessageList>
        </ChatLayout>
      </div>
    </div>
  );
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
  const threads = rows.map((r) => (waitingIn.has(r.id) ? { ...r, waiting: true } : r)).sort((a, b) => b.at - a.at);
  const matches = threads.filter((r) => !q || r.title.toLowerCase().includes(q));
  return (
    <div className="page flush session-page">
      <SessionTabs
        area="chat"
        activeId={threadId}
        tabs={threads.map((r) => ({ id: r.id, title: r.title, waiting: r.waiting, onSelect: () => open(threadSearch(r)) }))}
        onNew={() => open("new=1")}
        copyLink={() => copyText(location.href)}
        query={S.ui.chatQ}
        setQuery={(next) => ((S.ui.chatQ = next), render())}
      >
        {(close) => (
          <nav className="chat-list" aria-label="Conversations">
            {matches.length ? (
              matches.map((t) => <ThreadRow key={t.id} row={t} on={threadId === t.id} onPick={close} />)
            ) : (
              <p className="session-list-empty">{q ? "No conversation matches." : loaded ? "No conversations yet" : "Loading…"}</p>
            )}
          </nav>
        )}
      </SessionTabs>
      <section className="chat-main">
        {!isLive() && threadId ? (
          <DemoConversation key={threadId} id={threadId} />
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
            mode0={search.get("mode")}
          />
        )}
      </section>
    </div>
  );
}
