"use client";

import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Textarea } from "@pmagent/ui/components/textarea";
import { cn } from "@pmagent/ui/lib/utils";
import {
  ArrowUpIcon,
  BotIcon,
  CircleAlertIcon,
  CircleStopIcon,
  LayersIcon,
  Loader2Icon,
  NewspaperIcon,
  SparklesIcon,
  SquareIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

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

function Thinking({ run, writing = false }: { run: Run; writing?: boolean }) {
  return (
    <p className="text-muted-foreground flex items-center gap-2 text-sm">
      <Loader2Icon className="size-4 animate-spin" />
      {run.status === "queued" ? "Waiting to start…" : writing ? "Writing…" : "The PM is working on it…"}
    </p>
  );
}

/** What a run used, for owners and admins: "12,340 in / 512 out tokens · model". */
function RunUsage({ run }: { run: Run }) {
  if (isActive(run) || (run.input_tokens === 0 && run.output_tokens === 0)) return null;
  return (
    <p className="text-muted-foreground text-xs">
      {run.input_tokens.toLocaleString()} in / {run.output_tokens.toLocaleString()} out tokens
      {run.model && ` · ${run.model}`}
    </p>
  );
}

function RunView({
  run,
  scope,
  names,
  canDecide,
  showUsage,
}: {
  run: Run;
  scope: Scope;
  names: Map<string, string>;
  canDecide: boolean;
  showUsage: boolean;
}) {
  const who = run.requested_by_id ? (names.get(run.requested_by_id) ?? "Someone") : "Someone";
  const live = useRunStream(scope, run.id, isActive(run));
  return (
    <div className="grid gap-3">
      {run.kind === "chat" && runTitle(run) !== run.message && (
        <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <LayersIcon className="size-3.5" /> {who} asked the Architecture agent to {runTitle(run).toLowerCase()} ·{" "}
          {timeAgo(run.created_at)}
        </p>
      )}
      {run.kind === "chat" && runTitle(run) === run.message && (
        <div className="ml-auto grid max-w-[85%] gap-1">
          <span className="text-muted-foreground text-right text-xs">
            {who} · {timeAgo(run.created_at)}
          </span>
          <div className="bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-3 py-2 text-sm whitespace-pre-wrap">
            {run.message}
          </div>
        </div>
      )}
      {run.kind === "briefing" && (
        <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <NewspaperIcon className="size-3.5" /> {who} asked for the daily briefing · {timeAgo(run.created_at)}
        </p>
      )}
      <div className="flex gap-2">
        <span className="bg-brand text-brand-foreground mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full">
          <BotIcon className="size-3.5" />
        </span>
        <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)] gap-3">
          {isActive(run) && live && <Markdown>{live}</Markdown>}
          {isActive(run) && <Thinking run={run} writing={Boolean(live)} />}
          {wasStopped(run) && (
            <p className="text-muted-foreground flex items-center gap-1.5 text-sm">
              <CircleStopIcon className="size-4 shrink-0" />
              {run.error}.
            </p>
          )}
          {run.status === "failed" && !wasStopped(run) && (
            <p className="text-destructive flex items-start gap-1.5 text-sm">
              <CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
              {run.error ?? "The run failed."}
            </p>
          )}
          <RunApprovals run={run} scope={scope} canDecide={canDecide} />
          {run.status === "awaiting_approval" && (run.approvals ?? []).every((a) => a.status !== "pending") && (
            <Thinking run={{ ...run, status: "running" }} />
          )}
          {run.reply && <Markdown>{run.reply}</Markdown>}
          {run.status === "completed" && !run.reply?.trim() && (run.approvals ?? []).length === 0 && (
            <p className="text-muted-foreground text-sm">
              The PM finished without a reply. Models occasionally do this; ask again if you expected an answer or a
              change.
            </p>
          )}
          {showUsage && <RunUsage run={run} />}
        </div>
      </div>
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
  showUsage = false,
  compact,
}: {
  scope: Scope;
  threadId: string | null;
  onThread: (threadId: string) => void;
  names: Map<string, string>;
  canChat: boolean;
  canDecide: boolean;
  /** Each run's token usage (owners and admins). */
  showUsage?: boolean;
  compact?: boolean;
}) {
  const thread = useThread(scope, threadId);
  const send = useSendMessage(scope);
  const stop = useStopRun(scope);
  const briefing = useBriefing(scope);
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const runs = thread.data ?? [];
  const busy = runs.some(isActive) || runs.some((r) => r.status === "awaiting_approval") || send.isPending;
  const last = runs.at(-1);
  const working = runs.find(isActive);

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [runs.length, last?.status, last?.reply]);

  async function submit(message: string) {
    const text = message.trim();
    if (!text || busy) return;
    const run = await send.mutateAsync({ message: text, threadId }).catch(() => null);
    if (run) {
      setDraft("");
      if (run.thread_id !== threadId) onThread(run.thread_id);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void submit(draft);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className={cn("flex-1 overflow-y-auto", compact ? "p-3" : "p-4 md:p-6")}>
        <div className="mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)] gap-6">
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
                    Daily briefing
                  </Button>
                </div>
              )}
            </div>
          )}
          {runs.map((run) => (
            <RunView
              key={run.id}
              run={run}
              scope={scope}
              names={names}
              canDecide={canDecide}
              showUsage={showUsage}
            />
          ))}
          <div ref={bottom} />
        </div>
      </div>
      {canChat ? (
        <form onSubmit={onSubmit} className={cn("border-t", compact ? "p-3" : "p-4")}>
          <div className="bg-background focus-within:ring-ring/50 mx-auto flex max-w-3xl items-end gap-2 rounded-xl border p-2 focus-within:ring-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void submit(draft);
                }
              }}
              placeholder={
                busy
                  ? last?.status === "awaiting_approval"
                    ? "Decide the changes above to continue"
                    : "The PM is working…"
                  : threadId
                    ? "Reply to the PM"
                    : "Ask about the project, or ask for a change"
              }
              disabled={busy}
              rows={1}
              maxLength={20_000}
              className="max-h-40 min-h-9 flex-1 resize-none border-0 p-1.5 shadow-none focus-visible:ring-0"
              aria-label="Message the project manager"
            />
            {working ? (
              <Button
                type="button"
                size="icon"
                variant="secondary"
                className="size-8 shrink-0 rounded-lg"
                disabled={stop.isPending}
                onClick={() => stop.mutate(working.id)}
                aria-label="Stop"
                title="Stop"
              >
                {stop.isPending ? <Loader2Icon className="animate-spin" /> : <SquareIcon className="fill-current" />}
              </Button>
            ) : (
              <Button type="submit" size="icon" className="size-8 shrink-0 rounded-lg" disabled={busy || !draft.trim()} aria-label="Send">
                {send.isPending ? <Loader2Icon className="animate-spin" /> : <ArrowUpIcon />}
              </Button>
            )}
          </div>
          <p className="text-muted-foreground mx-auto mt-1.5 max-w-3xl text-[11px]">
            Enter to send, Shift+Enter for a new line. Nothing changes without your approval.
          </p>
        </form>
      ) : (
        <p className="text-muted-foreground border-t p-4 text-center text-sm">Guests can read, but not chat with the agents.</p>
      )}
    </div>
  );
}
