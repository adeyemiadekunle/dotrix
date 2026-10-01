"use client";

import { ChatMessage, ChatMessageMeta, ChatNotice } from "@pmagent/ui/components/chat-message";
import { BotIcon, ChevronDownIcon, CircleAlertIcon, CircleStopIcon } from "lucide-react";
import { useState } from "react";

import { Markdown } from "@/components/markdown";
import { agentLabel, isActive, useRunStream, wasStopped, type AgentOption, type Run } from "@/lib/agent";
import { useChatAgents } from "@/lib/agents";
import type { Scope } from "@/lib/issues";
import { agentName } from "@/lib/labels";

import { RunApprovals } from "./approvals";
import { RunOutputs } from "./run-outputs";

/** Who's answering: "Research agent", or "The agents" for Auto. */
function speaker(run: Run, options?: AgentOption[]): string {
  return run.agent && run.agent !== "auto" ? agentLabel(run.agent, options) : "The agents";
}

/** What the agent is doing, while it works: the live activity when there is one. */
function progressText(run: Run, activity: string | null, writing: boolean, options?: AgentOption[]): string {
  if (run.status === "queued") return "Waiting to start…";
  if (writing) return "Writing…";
  return activity ? `${activity}…` : `${speaker(run, options)} ${run.agent && run.agent !== "auto" ? "is" : "are"} working on it…`;
}

const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;

/** What a run used: "12,340 in (9,800 cached) / 512 out tokens · 3 model calls · model", and
 * on request where it went: by agent, tool results, files read, and the budget. The API
 * includes it only for owners and admins (null otherwise). */
export function RunUsage({ run }: { run: Run }) {
  const [open, setOpen] = useState(false);
  if (isActive(run) || run.input_tokens == null || run.output_tokens == null) return null;
  if (run.input_tokens === 0 && run.output_tokens === 0) return null;
  const cached = run.cached_input_tokens ?? 0;
  const calls = run.model_calls ?? 0;
  const breakdown = run.breakdown;
  const hasDetails = !!breakdown && (breakdown.by_agent.length > 0 || breakdown.tools.length > 0);
  return (
    <div className="text-muted-foreground grid gap-2 text-xs">
      <p>
        {run.input_tokens.toLocaleString()} in
        {cached > 0 && ` (${cached.toLocaleString()} cached)`} / {run.output_tokens.toLocaleString()} out tokens
        {calls > 0 && ` · ${plural(calls, "model call")}`}
        {run.model && ` · ${run.model}`}
        {hasDetails && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="hover:text-foreground ml-2 inline-flex items-center gap-0.5 underline-offset-2 hover:underline"
          >
            {open ? "Hide details" : "Details"}
            <ChevronDownIcon className={`size-3 transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
        )}
      </p>
      {open && breakdown && <UsageDetails run={run} breakdown={breakdown} />}
    </div>
  );
}

function UsageDetails({ run, breakdown }: { run: Run; breakdown: NonNullable<Run["breakdown"]> }) {
  const total = (run.input_tokens ?? 0) + (run.output_tokens ?? 0);
  return (
    <div className="bg-muted/50 grid gap-3 rounded-md border p-3">
      {breakdown.token_budget != null && (
        <p>
          Budget: {total.toLocaleString()} of {breakdown.token_budget.toLocaleString()} tokens (
          {Math.min(100, Math.round((total / breakdown.token_budget) * 100))}%)
        </p>
      )}
      {breakdown.by_agent.length > 0 && (
        <UsageList title="By agent">
          {breakdown.by_agent.map((a) => (
            <UsageRow key={a.agent} label={agentName(a.agent)}>
              {a.input_tokens.toLocaleString()} in / {a.output_tokens.toLocaleString()} out · {plural(a.model_calls, "call")}
            </UsageRow>
          ))}
        </UsageList>
      )}
      {(breakdown.by_stage ?? []).length > 0 && (
        <UsageList title="By stage">
          {(breakdown.by_stage ?? []).map((s) => (
            <UsageRow key={`${s.agent}/${s.stage}`} label={`${agentName(s.agent)}: ${s.stage.replaceAll("_", " ")}`}>
              {s.input_tokens.toLocaleString()} in / {s.output_tokens.toLocaleString()} out · {plural(s.model_calls, "call")}
            </UsageRow>
          ))}
        </UsageList>
      )}
      {breakdown.tools.length > 0 && (
        <UsageList title="Tool results (re-sent with every later call)">
          {breakdown.tools.map((t) => (
            <UsageRow key={t.tool} label={<code className="font-mono">{t.tool}</code>}>
              {plural(t.calls, "call")} · about {t.result_tokens.toLocaleString()} tokens
            </UsageRow>
          ))}
        </UsageList>
      )}
      {breakdown.files_read.length > 0 && (
        <UsageList title="Files read">
          {breakdown.files_read.map((f) => (
            <UsageRow key={f.path} label={<code className="font-mono break-all">{f.path.replace(/^\/pmagent\//, "")}</code>}>
              {f.times > 1 ? `${f.times} times` : "once"}
            </UsageRow>
          ))}
        </UsageList>
      )}
    </div>
  );
}

function UsageList({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1">
      <p className="text-foreground font-medium">{title}</p>
      <ul className="grid gap-0.5">{children}</ul>
    </div>
  );
}

function UsageRow({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex flex-wrap justify-between gap-x-4">
      <span className="min-w-0">{label}</span>
      <span className="tabular-nums">{children}</span>
    </li>
  );
}

/**
 * The agents' side of a run, wherever a run is shown (a conversation, the briefing page): who
 * answered, the reply as it streams, what the agent is doing meanwhile, changes waiting for
 * approval, the final reply or why it stopped, and the run's usage.
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
  const options = useChatAgents(scope);
  const decided = run.status === "awaiting_approval" && (run.approvals ?? []).every((a) => a.status !== "pending");
  return (
    <ChatMessage from="agent" avatar={avatar ? <BotIcon /> : undefined} className={className}>
      {run.kind === "chat" && <ChatMessageMeta>{agentLabel(run.agent, options)}</ChatMessageMeta>}
      {active && live.text && <Markdown>{live.text}</Markdown>}
      {active && <ChatNotice tone="progress">{progressText(run, live.activity, Boolean(live.text), options)}</ChatNotice>}
      {wasStopped(run) && <ChatNotice icon={<CircleStopIcon />}>{run.error}.</ChatNotice>}
      {run.status === "failed" && !wasStopped(run) && (
        <ChatNotice tone="destructive" icon={<CircleAlertIcon />}>
          {run.error ?? "The run failed."}
        </ChatNotice>
      )}
      <RunApprovals run={run} scope={scope} canDecide={canDecide} />
      {decided && <ChatNotice tone="progress">{speaker(run)} {run.agent && run.agent !== "auto" ? "is" : "are"} working on it…</ChatNotice>}
      {run.reply && <Markdown>{run.reply}</Markdown>}
      {/* Anyone who sees the project works the board; the API checks it again. */}
      <RunOutputs run={run} scope={scope} canAct />
      {run.status === "completed" && !run.reply?.trim() && (run.approvals ?? []).length === 0 && (
        <ChatNotice>
          {speaker(run)} finished without a reply. Models occasionally do this; ask again if you expected an answer or a
          change.
        </ChatNotice>
      )}
      <RunUsage run={run} />
    </ChatMessage>
  );
}
