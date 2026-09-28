"use client";

import { ChatMessage, ChatNotice } from "@pmagent/ui/components/chat-message";
import { BotIcon, CircleAlertIcon, CircleStopIcon } from "lucide-react";

import { Markdown } from "@/components/markdown";
import { isActive, useRunStream, wasStopped, type Run } from "@/lib/agent";
import type { Scope } from "@/lib/issues";

import { RunApprovals } from "./approvals";

/** What the PM is doing, while it works: the live activity when there is one. */
function progressText(run: Run, activity: string | null, writing: boolean): string {
  if (run.status === "queued") return "Waiting to start…";
  if (writing) return "Writing…";
  return activity ? `${activity}…` : "The PM is working on it…";
}

/** What a run used: "12,340 in (9,800 cached) / 512 out tokens · 3 model calls · model".
 * The API includes it only for owners and admins (null otherwise). */
export function RunUsage({ run }: { run: Run }) {
  if (isActive(run) || run.input_tokens == null || run.output_tokens == null) return null;
  if (run.input_tokens === 0 && run.output_tokens === 0) return null;
  const cached = run.cached_input_tokens ?? 0;
  const calls = run.model_calls ?? 0;
  return (
    <p className="text-muted-foreground text-xs">
      {run.input_tokens.toLocaleString()} in
      {cached > 0 && ` (${cached.toLocaleString()} cached)`} / {run.output_tokens.toLocaleString()} out tokens
      {calls > 0 && ` · ${calls} model call${calls === 1 ? "" : "s"}`}
      {run.model && ` · ${run.model}`}
    </p>
  );
}

/**
 * The PM's side of a run, wherever a run is shown (a conversation, the briefing page): the
 * reply as it streams, what the PM is doing meanwhile, changes waiting for approval, the
 * final reply or why it stopped, and the run's usage.
 */
export function AgentReply({
  run,
  scope,
  canDecide,
  avatar = true,
  className,
}: {
  run: Run;
  scope: Scope;
  canDecide: boolean;
  avatar?: boolean;
  className?: string;
}) {
  const active = isActive(run);
  const live = useRunStream(scope, run.id, active);
  const decided = run.status === "awaiting_approval" && (run.approvals ?? []).every((a) => a.status !== "pending");
  return (
    <ChatMessage from="agent" avatar={avatar ? <BotIcon /> : undefined} className={className}>
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
          The PM finished without a reply. Models occasionally do this; ask again if you expected an answer or a change.
        </ChatNotice>
      )}
      <RunUsage run={run} />
    </ChatMessage>
  );
}
