"use client";

import { Button } from "@pmagent/ui/components/button";
import { ChatBubble, ChatMessage, ChatMessageMeta, ChatNotice } from "@pmagent/ui/components/chat-message";
import { ChatScroller } from "@pmagent/ui/components/chat-scroller";
import { PromptInput, type PromptStatus } from "@pmagent/ui/components/prompt-input";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { BotIcon, CircleAlertIcon, CircleStopIcon, LayersIcon, NewspaperIcon, SparklesIcon } from "lucide-react";
import { useState } from "react";

import { timeAgo } from "@/components/issues/issue-activity";
import { Markdown } from "@/components/markdown";
import {
  isActive,
  runTitle,
  useBriefing,
  useRunStream,
  useSendMessage,
  useStopRun,
  useThread,
  wasStopped,
  type Run,
} from "@/lib/agent";
import type { Scope } from "@/lib/issues";

import { RunApprovals } from "./approvals";

const SUGGESTIONS = [
  "What's the state of the project?",
  "What should we build next, and why?",
  "Turn the latest requirements into an epic with stories",
];

/** What the PM is doing, while it works: the live activity when there is one. */
function progressText(run: Run, activity: string | null, writing: boolean): string {
  if (run.status === "queued") return "Waiting to start…";
  if (writing) return "Writing…";
  return activity ? `${activity}…` : "The PM is working on it…";
}

/** What a run used: "12,340 in / 512 out tokens · model". The API includes it only for
 * owners and admins (null otherwise). */
function RunUsage({ run }: { run: Run }) {
  if (isActive(run) || run.input_tokens == null || run.output_tokens == null) return null;
  if (run.input_tokens === 0 && run.output_tokens === 0) return null;
  return (
    <p className="text-muted-foreground text-xs">
      {run.input_tokens.toLocaleString()} in / {run.output_tokens.toLocaleString()} out tokens
      {run.model && ` · ${run.model}`}
    </p>
  );
}

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
  const active = isActive(run);
  const live = useRunStream(scope, run.id, active);
  const decided = run.status === "awaiting_approval" && (run.approvals ?? []).every((a) => a.status !== "pending");
  return (
    <div className="grid gap-3">
      <RunRequest run={run} who={who} />
      <ChatMessage from="agent" avatar={<BotIcon />}>
        {active && live.text && <Markdown>{live.text}</Markdown>}
        {active && <ChatNotice tone="progress">{progressText(run, live.activity, Boolean(live.text))}</ChatNotice>}
        {wasStopped(run) && <ChatNotice icon={<CircleStopIcon />}>{run.error}.</ChatNotice>}
        {run.status === "failed" && !wasStopped(run) && (
          <ChatNotice tone="destructive" icon={<CircleAlertIcon />}>
            {run.error ?? "The run failed."}
          </ChatNotice>
        )}
        <RunApprovals run={run} scope={scope} canDecide={canDecide} />
        {decided && <ChatNotice tone="progress">The PM is working on it…</ChatNotice>}
        {run.reply && <Markdown>{run.reply}</Markdown>}
        {run.status === "completed" && !run.reply?.trim() && (run.approvals ?? []).length === 0 && (
          <ChatNotice>
            The PM finished without a reply. Models occasionally do this; ask again if you expected an answer or a
            change.
          </ChatNotice>
        )}
        <RunUsage run={run} />
      </ChatMessage>
    </div>
  );
}

/**
 * One conversation with the PM and the box to continue it. The PM stays in Chat Mode (reads,
 * answers) unless told to change something; every change waits for approval.
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
  const runs = thread.data ?? [];
  const last = runs.at(-1);
  const working = runs.find(isActive);
  const waiting = runs.some((r) => r.status === "awaiting_approval");

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
    const run = await send.mutateAsync({ message: text, threadId }).catch(() => null);
    if (run) {
      setDraft("");
      if (run.thread_id !== threadId) onThread(run.thread_id);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ChatScroller
        followKey={threadId}
        contentClassName={cn("mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)] gap-6", compact ? "p-3" : "p-4 md:p-6")}
      >
        {threadId && thread.isLoading && <Skeleton className="h-24" />}
        {!threadId && (
          <div className="grid gap-4 py-6 text-center">
            <SparklesIcon className="text-brand mx-auto size-6" />
            <div className="grid gap-1">
              <p className="font-medium">Ask the project manager</p>
              <p className="text-muted-foreground text-sm">
                It reads the whole project and answers without changing anything. When you ask for a change, each one
                waits for your approval here.
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
            onValueChange={setDraft}
            onSubmit={(text) => void submit(text)}
            onStop={working ? () => stop.mutate(working.id) : undefined}
            status={status}
            label="Message the project manager"
            placeholder={
              status === "waiting" || last?.status === "awaiting_approval"
                ? "Decide the changes above to continue"
                : working
                  ? "The PM is working…"
                  : threadId
                    ? "Reply to the PM"
                    : "Ask about the project, or ask for a change"
            }
            hint="Enter to send, Shift+Enter for a new line. Nothing changes without your approval."
          />
        </div>
      ) : (
        <p className="text-muted-foreground border-t p-4 text-center text-sm">Guests can read, but not chat with the agents.</p>
      )}
    </div>
  );
}
