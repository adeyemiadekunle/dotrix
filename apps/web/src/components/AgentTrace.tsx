// An agent's work, as shadcn/ui's AI Elements show it (https://ui.shadcn.com/docs/ai-elements), on the shared Trace
// (@dotrix/ui/components/trace): Reasoning (what the model thought), Chain of Thought (the steps a reply took),
// Subagent (a specialist's task, its brief, result and evidence) and Tool (each of Kai's tool calls, a command
// opening onto its output). Chat and Codes both use them, so a step looks the same wherever it's shown.
import { useState, type ReactNode } from "react";

import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
  type TraceStatus,
} from "@dotrix/ui/components/trace";

import { agentName } from "@/lib/labels";
import type { SpecialistTask } from "@/lib/team";

import { Ic } from "../core/icons";
import { D } from "../data/store";
import { Face } from "../ui/face";

const Spinner = () => <Ic n="spinner-gap" cls="animate-spin" />;

/** The icon a line leads with: a spinner while it runs, a warning when it failed, else `done`. */
function StatusIcon({ status, done = "check-circle" }: { status?: TraceStatus; done?: string }) {
  return <TraceIcon>{status === "running" ? <Spinner /> : <Ic n={status === "error" ? "warning-circle" : done} />}</TraceIcon>;
}

/** Reasoning: "Thinking" while the model thinks (open, the latest of it as it comes), then "Thought", folded.
 *  Once the person opens or closes it, their choice wins. */
export function Reasoning({ text, live = false, seconds }: { text: string; live?: boolean; seconds?: number }) {
  const [open, setOpen] = useState<boolean>();
  const shown = live && text.length > 600 ? `…${text.slice(-600)}` : text;
  const line = (
    <TraceLine status={live ? "running" : undefined}>
      <TraceIcon>{live ? <Spinner /> : <Ic n="brain" />}</TraceIcon>
      <TraceTitle>{live ? "Thinking" : "Thought"}</TraceTitle>
      {seconds ? <TraceDescription>{seconds}s</TraceDescription> : null}
    </TraceLine>
  );
  if (!text) return <Trace className="agent-trace">{line}</Trace>;
  return (
    <Trace className="agent-trace">
      <TraceCollapsible open={open ?? live} onOpenChange={setOpen}>
        <TraceCollapsibleTrigger aria-label={live ? "Thinking" : "Thought"}>{line}</TraceCollapsibleTrigger>
        <TraceCollapsibleContent className="agent-trace-text" aria-live={live ? "polite" : undefined}>
          {shown}
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

/** Chain of Thought: a reply's steps folded into one line ("Worked through 4 steps"), each a line of its own when open.
 *  While the reply works its latest step shimmers. `thinking` (kept after the run) goes first, as Reasoning. */
export function ChainOfThought({
  steps,
  running = false,
  thinking,
  loading = false,
  title,
  defaultOpen,
  onOpenChange,
}: {
  steps: string[];
  running?: boolean;
  thinking?: string;
  loading?: boolean;
  title?: string;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const label = title ?? (running ? (steps.at(-1) ?? "Working") : `Worked through ${steps.length} step${steps.length === 1 ? "" : "s"}`);
  return (
    <Trace className="agent-trace">
      <TraceCollapsible defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
        <TraceCollapsibleTrigger>
          <TraceLine status={running ? "running" : undefined}>
            <TraceIcon>{running ? <Spinner /> : <Ic n="list-checks" />}</TraceIcon>
            <TraceTitle>{label}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          {thinking ? <Reasoning text={thinking} /> : null}
          <Trace role="list" aria-label="Steps">
            {steps.length ? (
              steps.map((step, i) => {
                const status = running && i === steps.length - 1 ? "running" : undefined;
                return (
                  <TraceLine key={i} role="listitem" status={status}>
                    <StatusIcon status={status} />
                    <TraceTitle title={step}>{step}</TraceTitle>
                  </TraceLine>
                );
              })
            ) : (
              <TraceLine role="listitem" status="pending">
                <TraceIcon>{loading ? <Spinner /> : <Ic n="clock" />}</TraceIcon>
                <TraceTitle>{loading ? "Loading…" : "No steps kept"}</TraceTitle>
              </TraceLine>
            )}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

const TASK_STATUS: Record<SpecialistTask["status"], [string, TraceStatus | undefined]> = {
  queued: ["Waiting to start", "pending"],
  waiting_dependency: ["Waiting on another task", "pending"],
  waiting_children: ["Working", "running"],
  running: ["Working", "running"],
  awaiting_approval: ["Waiting for approval", undefined],
  completed: ["Done", undefined],
  failed: ["Didn't finish", "error"],
  blocked: ["Blocked", "error"],
  cancelled: ["Stopped", "pending"],
};

/** Subagent: one specialist's task. The line names the agent and what it's doing; open, its brief, then what it
 *  found: the summary, findings, risks and the evidence it cited. `children` (an approval) goes last. */
function Subagent({ task, children }: { task: SpecialistTask; children?: ReactNode }) {
  const [said, status] = TASK_STATUS[task.status] ?? [task.status.replaceAll("_", " "), undefined];
  const agent = D().agents.find((a) => a.handle === task.agent);
  const name = agent?.name ?? agentName(task.agent ?? "auto");
  const result = task.task_result;
  const waiting = task.status === "awaiting_approval";
  return (
    <TraceCollapsible defaultOpen={waiting}>
      <TraceCollapsibleTrigger>
        <TraceLine status={status}>
          <TraceIcon>{status === "running" ? <Spinner /> : <Face c={agent?.c ?? "#57544E"} size={16} mood="idle" />}</TraceIcon>
          <TraceTitle>
            {status === "running" ? `${name} is working` : name}
            {agent?.role ? <span className="agent-trace-role"> · {agent.role}</span> : null}
          </TraceTitle>
          {status === "running" ? null : <TraceDescription>{said}</TraceDescription>}
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="agent-trace-sub">
        {task.task_key ? <span className="badge mono">{task.task_key}</span> : null}
        {task.message ? <p className="agent-trace-brief">{task.message}</p> : null}
        {result?.summary ? <p className="agent-trace-result">{result.summary}</p> : task.error ? <p className="agent-trace-error">{task.error}</p> : null}
        {result?.findings?.length || result?.risks?.length ? (
          <Trace aria-label="Findings">
            {result.findings?.map((f, i) => (
              <TraceLine key={`f${i}`}>
                <TraceIcon>
                  <Ic n="magnifying-glass" />
                </TraceIcon>
                <TraceTitle className="agent-trace-wrap">{f}</TraceTitle>
              </TraceLine>
            ))}
            {result.risks?.map((r, i) => (
              <TraceLine key={`r${i}`}>
                <TraceIcon>
                  <Ic n="warning-circle" />
                </TraceIcon>
                <TraceTitle className="agent-trace-wrap">{r}</TraceTitle>
              </TraceLine>
            ))}
          </Trace>
        ) : null}
        {result?.evidence?.length ? (
          <div className="agent-trace-sources" aria-label="Evidence">
            {result.evidence.map((ref, i) => (
              <span key={i} className="agent-trace-source mono" title={ref}>
                {ref}
              </span>
            ))}
          </div>
        ) : null}
        {children}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/** The specialists a reply involved, one Subagent line each. */
export function Subagents({ tasks, approval }: { tasks: SpecialistTask[]; approval?: (task: SpecialistTask) => ReactNode }) {
  if (!tasks.length) return null;
  return (
    <section className="agent-trace agent-trace-subagents" aria-label="Specialist activity">
      <Trace>
        {tasks.map((task) => (
          <Subagent key={task.id} task={task}>
            {task.status === "awaiting_approval" ? approval?.(task) : null}
          </Subagent>
        ))}
      </Trace>
    </section>
  );
}

export interface ToolEvent {
  kind: string;
  text: string;
  at?: string;
  ref?: string | null;
}

/** What a tool line does, from the words the coding engine's step starts with. */
function toolIcon(text: string): string {
  if (/^Ran\b/.test(text)) return "terminal-window";
  if (/^(Edited|Wrote|Created)\b/.test(text)) return "pencil-simple";
  if (/^Deleted\b/.test(text)) return "x-circle";
  if (/^Read\b/.test(text)) return "file";
  if (/^(Searched|Found|Grep|Glob|Listed)\b/i.test(text)) return "magnifying-glass";
  if (/^(Fetched|Browsed|Opened)\b/.test(text)) return "globe";
  if (/^Started\b/.test(text)) return "flow-arrow";
  return "check-circle";
}

const LONG = 24; // lines of a command's output shown before "Show all"

function Output({ text, failed }: { text: string; failed: boolean }) {
  const [all, setAll] = useState(false);
  const lines = text.split("\n");
  const long = lines.length > LONG;
  return (
    <div className={`agent-trace-output${failed ? " bad" : ""}`}>
      <pre className="mono">{long && !all ? lines.slice(-LONG).join("\n") : text}</pre>
      {long && (
        <button className="btn btn-xs btn-ghost" onClick={() => setAll(!all)}>
          {all ? "Show less" : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}

/** Tool: each of a coding turn's tool calls as a line; a command opens onto the output it printed (paired by `ref`),
 *  a failed one is red, and while the turn works its latest call shimmers. `render` turns a line's text into links. */
export function ToolCalls({ events, running = false, render }: { events: ToolEvent[]; running?: boolean; render?: (text: string) => ReactNode }) {
  const out = new Map<string, { text: string; failed: boolean }>();
  for (const e of events) {
    if ((e.kind === "output" || e.kind === "output-error") && e.ref) {
      const prev = out.get(e.ref);
      out.set(e.ref, { text: prev ? `${prev.text}\n${e.text}` : e.text, failed: (prev?.failed ?? false) || e.kind === "output-error" });
    }
  }
  const calls = events.filter((e) => e.kind !== "text" && !e.kind.startsWith("output"));
  return (
    <Trace className="agent-trace" aria-label="Tool calls">
      {calls.map((e, i) => {
        const output = e.ref ? out.get(e.ref) : undefined;
        const status: TraceStatus | undefined = e.kind === "error" || output?.failed ? "error" : running && i === calls.length - 1 ? "running" : undefined;
        const line = (
          <TraceLine status={status}>
            <StatusIcon status={status} done={toolIcon(e.text)} />
            <TraceTitle title={e.text}>{render && !output?.text ? render(e.text) : e.text}</TraceTitle>
          </TraceLine>
        );
        if (!output?.text) return <div key={i}>{line}</div>;
        return (
          <TraceCollapsible key={i} defaultOpen={output.failed && !running}>
            <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
            <TraceCollapsibleContent>
              <Output text={output.text} failed={output.failed} />
            </TraceCollapsibleContent>
          </TraceCollapsible>
        );
      })}
    </Trace>
  );
}
