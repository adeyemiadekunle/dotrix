import { Button } from "@dotrix/ui/components/button";
import { ChatBubble, ChatMessage, ChatMessageMeta } from "@dotrix/ui/components/chat-message";
import { ChatScroller } from "@dotrix/ui/components/chat-scroller";
import { PromptInput, type PromptStatus } from "@dotrix/ui/components/prompt-input";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { cn } from "@dotrix/ui/lib/utils";
import { CpuIcon, LayersIcon, NewspaperIcon, SparklesIcon } from "lucide-react";
import { useRef, useState } from "react";

import { timeAgo } from "@/components/issues/issue-activity";
import { useMentionable, useMentions } from "@/components/mentions";
import {
  agentLabel,
  isActive,
  mentionedAgent,
  modelName,
  runTitle,
  useBriefing,
  useModels,
  useSendMessage,
  useStopRun,
  useThread,
  type AgentId,
  type Run,
} from "@/lib/agent";
import { useChatAgents } from "@/lib/agents";
import type { Scope } from "@/lib/issues";
import { can } from "@/lib/labels";
import { useWorkspaceProject } from "@/lib/queries";

import { AgentPicker } from "./agent-picker";
import { AgentReply } from "./agent-reply";

// Shown only on a new conversation.
const SUGGESTIONS = [
  "Summarise the project: what moved, what's blocked, and what's due this week",
  "What changed since yesterday?",
  "What should we build next, and why?",
  "Turn the latest requirements into an epic with stories",
];

/** Who asked, and what: the person's message, or a line for built-in requests. */
function RunRequest({ run, who }: { run: Run; who: string }) {
  const when = timeAgo(run.created_at);
  if (run.kind === "briefing") {
    return (
      <ChatMessageMeta>
        <NewspaperIcon /> {who} asked for the daily briefing · {when}
      </ChatMessageMeta>
    );
  }
  if (runTitle(run) !== run.message) {
    return (
      <ChatMessageMeta>
        <LayersIcon /> {who} asked the Architecture agent to {runTitle(run).toLowerCase()} · {when}
      </ChatMessageMeta>
    );
  }
  return (
    <ChatMessage from="user">
      <ChatMessageMeta>
        {who} · {when}
      </ChatMessageMeta>
      <ChatBubble>{run.message}</ChatBubble>
    </ChatMessage>
  );
}

function RunView({ run, scope, names, canDecide }: { run: Run; scope: Scope; names: Map<string, string>; canDecide: boolean }) {
  const who = run.requested_by_id ? (names.get(run.requested_by_id) ?? "Someone") : "Someone";
  return (
    <div className="grid gap-3">
      <RunRequest run={run} who={who} />
      <AgentReply run={run} scope={scope} canDecide={canDecide} />
    </div>
  );
}

/**
 * One conversation with the project's agents and the box to continue it. The + menu picks who
 * answers (Auto, or one specialist) and, before the first message, the model the whole
 * conversation runs on. Agents stay in Chat Mode (read, answer) unless told to change
 * something; every change waits for approval.
 */
export function Conversation({
  scope,
  threadId,
  onThread,
  names,
  canChat,
  canDecide,
  compact,
  initialDraft,
}: {
  scope: Scope;
  threadId: string | null;
  onThread: (threadId: string) => void;
  names: Map<string, string>;
  canChat: boolean;
  canDecide: boolean;
  compact?: boolean;
  /** What the message box starts with (from search); "@handle …" picks that agent. */
  initialDraft?: string;
}) {
  const thread = useThread(scope, threadId);
  const send = useSendMessage(scope);
  const stop = useStopRun(scope);
  const briefing = useBriefing(scope);
  const { workspace, project } = useWorkspaceProject(scope.projectId);
  const models = useModels(workspace?.id);
  const agentOptions = useChatAgents(scope);
  const [start] = useState(() => {
    const mention = initialDraft ? mentionedAgent(initialDraft, agentOptions) : null;
    return { draft: mention ? mention[1] : (initialDraft ?? ""), agent: mention?.[0] };
  });
  const [draft, setDraft] = useState(start.draft);
  const input = useRef<HTMLTextAreaElement>(null);
  const mentionable = useMentionable(scope.workspaceId, scope.projectId);
  const people = useMentions({ people: mentionable, value: draft, onValueChange: setDraft, inputRef: input });
  // Picks made here, for this conversation (a new one has no thread yet).
  const [pick, setPick] = useState<{ thread: string | null; agent?: AgentId; model?: string | null }>({
    thread: threadId,
    agent: start.agent,
  });
  const picked = pick.thread === threadId ? pick : { thread: threadId };
  const runs = thread.data ?? [];
  const last = runs.at(-1);
  const working = runs.find(isActive);
  const waiting = runs.some((r) => r.status === "awaiting_approval");
  // The conversation keeps the last agent picked until it's changed.
  const agent: AgentId = picked.agent ?? ((last?.agent as AgentId | undefined) || "auto");
  const projectModel = project?.model ?? "";
  // A conversation's model is fixed once it starts; a new one may choose.
  const fixedModel = threadId ? (runs[0]?.conversation_model ?? (runs.length ? projectModel : null)) : null;
  const mayChooseModel = !threadId && can(workspace, "agents:choose_model");
  const setAgent = (next: AgentId) => setPick({ ...picked, agent: next });
  // An "@handle " typed before the workspace's agents loaded is picked once they arrive.
  const [optionsSeen, setOptionsSeen] = useState(agentOptions);
  if (optionsSeen !== agentOptions) {
    setOptionsSeen(agentOptions);
    const mention = mentionedAgent(draft, agentOptions);
    if (mention) {
      setAgent(mention[0]);
      setDraft(mention[1]);
    }
  }

  const status: PromptStatus = stop.isPending ? "stopping" : working ? "working" : send.isPending ? "sending" : waiting ? "waiting" : "ready";

  async function submit(text: string) {
    if (status !== "ready") return;
    // Sent before the mention was picked up: pick it now.
    const mention = mentionedAgent(text, agentOptions);
    const who = mention ? mention[0] : agent;
    const run = await send
      .mutateAsync({
        message: mention ? mention[1] : text,
        threadId,
        agent: who,
        model: threadId ? null : (picked.model ?? null),
        mentions: people.mentioned(text),
      })
      .catch(() => null);
    if (run) {
      setDraft("");
      people.reset();
      if (run.thread_id !== threadId) {
        setPick({ thread: run.thread_id, agent: who });
        onThread(run.thread_id);
      }
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ChatScroller
        followKey={threadId}
        follow={Boolean(threadId)} // a new chat's welcome screen reads from the top
        contentClassName={cn("mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)] gap-6", compact ? "p-3" : "p-4 md:p-6")}
      >
        {threadId && thread.isLoading && <Skeleton className="h-24" />}
        {fixedModel && (
          <p className="text-muted-foreground flex items-center justify-center gap-1.5 text-xs">
            <CpuIcon className="size-3.5" />
            This conversation runs on <span className="font-mono">{modelName(fixedModel)}</span>
          </p>
        )}
        {!threadId && (
          <div className="grid gap-4 py-6 text-center">
            <SparklesIcon className="text-brand mx-auto size-6" />
            <div className="grid gap-1">
              <p className="font-medium">Chat with the project&apos;s agents</p>
              <p className="text-muted-foreground text-sm">
                They read the whole project and answer without changing anything. Use + to pick who answers (Auto brings in the specialists it needs) and the
                model. When you ask for a change, each one waits for approval here.
              </p>
            </div>
            {canChat && (
              <div className="grid gap-2">
                {SUGGESTIONS.map((s) => (
                  <Button key={s} variant="outline" size="sm" className="h-auto justify-start py-2 text-left whitespace-normal" onClick={() => void submit(s)}>
                    {s}
                  </Button>
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={briefing.isPending}
                  onClick={async () => {
                    const run = await briefing.mutateAsync().catch(() => null);
                    if (run) onThread(run.thread_id);
                  }}
                >
                  <NewspaperIcon />
                  Quick summary from the board
                </Button>
              </div>
            )}
          </div>
        )}
        {runs.map((run) => (
          <RunView key={run.id} run={run} scope={scope} names={names} canDecide={canDecide} />
        ))}
      </ChatScroller>
      {canChat ? (
        <div className={cn("border-t", compact ? "p-3" : "p-4")}>
          <PromptInput
            className="mx-auto w-full max-w-3xl"
            value={draft}
            inputRef={input}
            onKeyDown={people.onKeyDown}
            above={people.list}
            onValueChange={(value) => {
              // "@research " at the start picks that agent; "@" elsewhere offers people to mention.
              const mention = mentionedAgent(value, agentOptions);
              if (mention) {
                setAgent(mention[0]);
                setDraft(mention[1]);
                people.track(mention[1], null);
              } else {
                setDraft(value);
                people.track(value, input.current?.selectionStart ?? value.length);
              }
            }}
            onSubmit={(text) => void submit(text)}
            onStop={working ? () => stop.mutate(working.id) : undefined}
            status={status}
            label={`Message ${agent === "auto" ? "the agents" : agentLabel(agent, agentOptions)}`}
            footer={
              <>
                <AgentPicker
                  agent={agent}
                  onAgent={setAgent}
                  options={agentOptions}
                  model={picked.model ?? null}
                  onModel={mayChooseModel ? (model) => setPick({ ...picked, model }) : undefined}
                  models={(models.data ?? []).map((m) => m.id)}
                  defaultModel={projectModel}
                  disabled={status !== "ready"}
                />
                <span className="flex-1" />
                {!picked.model && (fixedModel ?? projectModel) && (
                  <span className="text-muted-foreground truncate font-mono text-[11px]" title="The model this conversation runs on">
                    {modelName(fixedModel ?? projectModel)}
                  </span>
                )}
              </>
            }
            placeholder={
              status === "waiting" || last?.status === "awaiting_approval"
                ? "Decide the changes above to continue"
                : working
                  ? `${working.agent === "auto" ? "The agents are" : `${agentLabel(working.agent, agentOptions)} is`} working…`
                  : threadId
                    ? "Reply"
                    : "Ask about the project, or ask for a change (@ picks an agent)"
            }
          />
        </div>
      ) : (
        <p className="text-muted-foreground border-t p-4 text-center text-sm">Guests can read, but not chat with the agents.</p>
      )}
    </div>
  );
}
