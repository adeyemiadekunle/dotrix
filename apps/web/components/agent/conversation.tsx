"use client";

import { Button } from "@pmagent/ui/components/button";
import { ChatBubble, ChatMessage, ChatMessageMeta } from "@pmagent/ui/components/chat-message";
import { ChatScroller } from "@pmagent/ui/components/chat-scroller";
import { PromptInput, type PromptStatus } from "@pmagent/ui/components/prompt-input";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { CpuIcon, LayersIcon, NewspaperIcon, SparklesIcon } from "lucide-react";
import { useState } from "react";

import { timeAgo } from "@/components/issues/issue-activity";
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
import { useCurrentProject } from "@/lib/queries";

import { AgentPicker } from "./agent-picker";
import { AgentReply } from "./agent-reply";

const SUGGESTIONS = [
  "What's the state of the project?",
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

function RunView({
  run,
  scope,
  names,
  canDecide,
}: {
  run: Run;
  scope: Scope;
  names: Map<string, string>;
  canDecide: boolean;
}) {
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
}: {
  scope: Scope;
  threadId: string | null;
  onThread: (threadId: string) => void;
  names: Map<string, string>;
  canChat: boolean;
  canDecide: boolean;
  compact?: boolean;
}) {
  const thread = useThread(scope, threadId);
  const send = useSendMessage(scope);
  const stop = useStopRun(scope);
  const briefing = useBriefing(scope);
  const [draft, setDraft] = useState("");
  const { workspace, project } = useCurrentProject();
  const models = useModels(workspace?.id);
  const agentOptions = useChatAgents(scope);
  // Picks made here, for this conversation (a new one has no thread yet).
  const [pick, setPick] = useState<{ thread: string | null; agent?: AgentId; model?: string | null }>({
    thread: threadId,
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

  const status: PromptStatus = stop.isPending
    ? "stopping"
    : working
      ? "working"
      : send.isPending
        ? "sending"
        : waiting
          ? "waiting"
          : "ready";

  async function submit(text: string) {
    if (status !== "ready") return;
    const run = await send
      .mutateAsync({ message: text, threadId, agent, model: threadId ? null : (picked.model ?? null) })
      .catch(() => null);
    if (run) {
      setDraft("");
      if (run.thread_id !== threadId) {
        setPick({ thread: run.thread_id, agent });
        onThread(run.thread_id);
      }
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ChatScroller
        followKey={threadId}
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
                They read the whole project and answer without changing anything. Use + to pick who answers (Auto brings
                in the specialists it needs) and the model. When you ask for a change, each one waits for approval here.
              </p>
            </div>
            {canChat && (
              <div className="grid gap-2">
                {SUGGESTIONS.map((s) => (
                  <Button
                    key={s}
                    variant="outline"
                    size="sm"
                    className="h-auto justify-start py-2 text-left whitespace-normal"
                    onClick={() => void submit(s)}
                  >
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
                  Daily briefing
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
            onValueChange={(value) => {
              // "@research " at the start picks that agent.
              const mention = mentionedAgent(value, agentOptions);
              if (mention) {
                setAgent(mention[0]);
                setDraft(mention[1]);
              } else {
                setDraft(value);
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
