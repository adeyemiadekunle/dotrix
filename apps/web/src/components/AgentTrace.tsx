// An agent's work, as shadcn/ui's AI Elements show it (https://ui.shadcn.com/docs/ai-elements), on the shared Trace
// (@dotrix/ui/components/trace): Reasoning (what the model thought), Chain of Thought (the steps a reply took),
// Subagent (a specialist's task, its brief, result and evidence), Tool (each of Kai's tool calls, a command
// opening onto its output), Terminal, Test Results and Stack Trace (what a command printed, read), Plan and Queue
// (steps to do, messages waiting), Sources and Inline Citation (what a reply read), Confirmation (a change waiting
// for a person), Checkpoint (a turn's commit) and Context (a reply's tokens). Chat and Codes both use them, so a
// step looks the same wherever it's shown.
import { useState, type ReactNode } from "react";

import { HoverCard, HoverCardContent, HoverCardTrigger } from "@dotrix/ui/components/hover-card";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@dotrix/ui/components/item";
import { Marker, MarkerContent, MarkerIcon } from "@dotrix/ui/components/marker";

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
import type { Schemas } from "@/lib/api";
import type { SpecialistTask } from "@/lib/team";

import { parseStack, parseTests, repoPath, type StackTrace, type TestRun } from "../core/agentOutput";

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

/** A command's output as it printed it: the last lines, with "Show all". */
function Output({ text, failed, className = "" }: { text: string; failed: boolean; className?: string }) {
  const [all, setAll] = useState(false);
  const lines = text.split("\n");
  const long = lines.length > LONG;
  return (
    <div className={`agent-trace-output${failed ? " bad" : ""} ${className}`}>
      <pre className="mono">{long && !all ? lines.slice(-LONG).join("\n") : text}</pre>
      {long && (
        <button className="btn btn-xs btn-ghost" onClick={() => setAll(!all)}>
          {all ? "Show less" : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "23 passed, 1 failed, 2 skipped". */
function testsSaid(run: TestRun): string {
  return (
    [run.passed && `${run.passed} passed`, run.failed && `${run.failed} failed`, run.skipped && `${run.skipped} skipped`].filter(Boolean).join(", ") ||
    "No tests ran"
  );
}

/** Test Results: the run's counts as a line, opening onto each failing test (and what it said, when it said it). */
function TestResults({ run, defaultOpen }: { run: TestRun; defaultOpen?: boolean }) {
  const total = run.passed + run.failed + run.skipped;
  const status = run.failed ? "error" : undefined;
  const line = (
    <TraceLine status={status}>
      <TraceIcon>
        <Ic n="flask" />
      </TraceIcon>
      <TraceTitle>Ran {plural(total, "test")}</TraceTitle>
      <TraceDescription>{testsSaid(run)}</TraceDescription>
    </TraceLine>
  );
  if (!run.failed) return <Trace className="agent-trace agent-tests">{line}</Trace>;
  return (
    <Trace className="agent-trace agent-tests">
      <TraceCollapsible defaultOpen={defaultOpen ?? true}>
        <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace aria-label="Failing tests">
            {run.failures.length ? (
              run.failures.map((f) =>
                f.detail ? (
                  <TraceCollapsible key={f.name}>
                    <TraceCollapsibleTrigger>
                      <TraceLine status="error">
                        <TraceIcon>
                          <Ic n="x" />
                        </TraceIcon>
                        <TraceTitle className="mono">{f.name}</TraceTitle>
                      </TraceLine>
                    </TraceCollapsibleTrigger>
                    <TraceCollapsibleContent>
                      <Output text={f.detail} failed />
                    </TraceCollapsibleContent>
                  </TraceCollapsible>
                ) : (
                  <TraceLine key={f.name} status="error">
                    <TraceIcon>
                      <Ic n="x" />
                    </TraceIcon>
                    <TraceTitle className="mono" title={f.name}>
                      {f.name}
                    </TraceTitle>
                  </TraceLine>
                ),
              )
            ) : (
              <TraceLine status="pending">
                <TraceIcon>
                  <Ic n="question" />
                </TraceIcon>
                <TraceTitle>The output doesn't name the failing tests</TraceTitle>
              </TraceLine>
            )}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

/** Stack Trace: "Failed: <error>", opening onto the full error and its frames; the project's own frames first and
 *  linked to Files (`onPath`), a library's folded under one line of their own. */
function StackTraceView({ stack, onPath, known }: { stack: StackTrace; onPath?: (path: string, line?: number) => void; known?: string[] }) {
  const own = stack.frames.filter((f) => !f.vendor);
  const vendor = stack.frames.filter((f) => f.vendor);
  const frame = (f: StackTrace["frames"][number], i: number) => {
    const path = onPath ? repoPath(f.file, known) : undefined;
    return (
      <li key={i}>
        {path ? (
          <button type="button" className="path-link mono" onClick={() => onPath!(path, f.line)} data-tip="Open in Files">
            {f.text}
          </button>
        ) : (
          f.text
        )}
      </li>
    );
  };
  return (
    <Trace className="agent-trace agent-stack">
      <TraceCollapsible defaultOpen>
        <TraceCollapsibleTrigger>
          <TraceLine status="error">
            <TraceIcon>
              <Ic n="x-circle" />
            </TraceIcon>
            <TraceTitle>Failed: {stack.error}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <div className="agent-stack-box mono">
            <p className="agent-stack-error">{stack.error}</p>
            {own.length > 0 && <ol aria-label="Stack frames">{own.map(frame)}</ol>}
            {vendor.length > 0 && (
              <Trace>
                <TraceCollapsible>
                  <TraceCollapsibleTrigger>
                    <TraceLine>
                      <TraceIcon>
                        <Ic n="stack" />
                      </TraceIcon>
                      <TraceTitle>{plural(vendor.length, "library frame")}</TraceTitle>
                    </TraceLine>
                  </TraceCollapsibleTrigger>
                  <TraceCollapsibleContent>
                    <ol className="agent-stack-vendor">{vendor.map(frame)}</ol>
                  </TraceCollapsibleContent>
                </TraceCollapsible>
              </Trace>
            )}
          </div>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

/** What a command printed, read: its tests and the last stack trace in it, each shown as such. */
export function OutputReading({
  text,
  failed,
  onPath,
  known,
}: {
  text: string;
  failed: boolean;
  onPath?: (path: string, line?: number) => void;
  known?: string[];
}) {
  const tests = parseTests(text);
  const stack = failed || !tests ? parseStack(text) : null;
  if (!tests && !stack) return null;
  return (
    <div className="agent-reading">
      {tests && <TestResults run={tests} />}
      {stack && <StackTraceView stack={stack} onPath={onPath} known={known} />}
    </div>
  );
}

/** Tool: each of a coding turn's tool calls as a line; a command opens onto the output it printed (paired by `ref`),
 *  read for its tests and stack trace, a failed one is red, and while the turn works its latest call shimmers.
 *  `render` turns a line's text into links; `onPath` opens a stack frame's file. */
export function ToolCalls({
  events,
  running = false,
  render,
  onPath,
  known,
}: {
  events: ToolEvent[];
  running?: boolean;
  render?: (text: string) => ReactNode;
  onPath?: (path: string, line?: number) => void;
  known?: string[];
}) {
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
        const tests = output?.text ? parseTests(output.text) : null;
        const failed = !!output?.failed || !!tests?.failed;
        const status: TraceStatus | undefined = e.kind === "error" || failed ? "error" : running && i === calls.length - 1 ? "running" : undefined;
        const line = (
          <TraceLine status={status}>
            <StatusIcon status={status} done={tests ? "flask" : toolIcon(e.text)} />
            <TraceTitle title={e.text}>{render && !output?.text ? render(e.text) : e.text}</TraceTitle>
            {tests && <TraceDescription>{testsSaid(tests)}</TraceDescription>}
          </TraceLine>
        );
        if (!output?.text) return <div key={i}>{line}</div>;
        return (
          <TraceCollapsible key={i} defaultOpen={failed && !running}>
            <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
            <TraceCollapsibleContent>
              <OutputReading text={output.text} failed={failed} onPath={onPath} known={known} />
              <Output text={output.text} failed={output.failed} />
            </TraceCollapsibleContent>
          </TraceCollapsible>
        );
      })}
    </Trace>
  );
}

type Source = Schemas["SourceRead"];

const TIER: Record<Source["tier"], string> = { primary: "Primary source", reputable: "Reputable source", other: "Other source" };

/** Inline Citation: "[S1]" in a reply as a chip naming the site; hovering it shows the page it stands for. */
export function Citation({ source }: { source: Source }) {
  return (
    <HoverCard>
      <HoverCardTrigger asChild>
        <a className="agent-cite" href={source.url} target="_blank" rel="noreferrer noopener">
          {source.host || source.label}
          <span className="sr-only"> ({source.label}, opens in a new tab)</span>
        </a>
      </HoverCardTrigger>
      <HoverCardContent className="agent-cite-card" align="start">
        <div className="agent-cite-title">{source.title || source.url}</div>
        <div className="agent-cite-meta">
          <span className="mono">{source.label}</span>
          <span>{source.host}</span>
          <span>{TIER[source.tier]}</span>
          {source.published && <span>{source.published.slice(0, 10)}</span>}
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}

/** Sources: "Used 3 sources", opening onto each page the reply read, its label first (S1, S2, …). */
export function Sources({ sources }: { sources: Source[] }) {
  const seen = sources.filter((s, i) => sources.findIndex((o) => o.url === s.url) === i);
  if (!seen.length) return null;
  return (
    <Trace className="agent-trace">
      <TraceCollapsible>
        <TraceCollapsibleTrigger>
          <TraceLine>
            <TraceIcon>
              <Ic n="globe" />
            </TraceIcon>
            <TraceTitle>Used {plural(seen.length, "source")}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace aria-label="Sources">
            {seen.map((source) => (
              <a key={source.url} href={source.url} target="_blank" rel="noreferrer noopener">
                <TraceLine>
                  <TraceIcon>
                    <Ic n={source.kind === "search" ? "magnifying-glass" : "globe"} />
                  </TraceIcon>
                  <TraceTitle>
                    <span className="mono agent-source-label">{source.label}</span> {source.title || source.host}
                    <span className="sr-only"> (opens in a new tab)</span>
                  </TraceTitle>
                  <TraceDescription>{source.host}</TraceDescription>
                  <TraceIcon>
                    <Ic n="arrow-up-right" />
                  </TraceIcon>
                </TraceLine>
              </a>
            ))}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

export interface PlanStep {
  title: string;
  detail?: string;
  note?: string;
}

/** Plan: a numbered list of steps under one line ("3 tasks"), open; a step with detail opens onto it. */
export function PlanSteps({
  title,
  steps,
  icon = "list-checks",
  defaultOpen = true,
}: {
  title: string;
  steps: PlanStep[];
  icon?: string;
  defaultOpen?: boolean;
}) {
  if (!steps.length) return null;
  return (
    <Trace className="agent-trace agent-plan">
      <TraceCollapsible defaultOpen={defaultOpen}>
        <TraceCollapsibleTrigger>
          <TraceLine>
            <TraceIcon>
              <Ic n={icon} />
            </TraceIcon>
            <TraceTitle>{title}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace role="list" aria-label={title}>
            {steps.map((step, i) => {
              const line = (
                <TraceLine role={step.detail ? undefined : "listitem"}>
                  <TraceIcon className="agent-plan-n">{i + 1}</TraceIcon>
                  <TraceTitle className="agent-trace-wrap">{step.title}</TraceTitle>
                  {step.note && <TraceDescription>{step.note}</TraceDescription>}
                </TraceLine>
              );
              return step.detail ? (
                <TraceCollapsible key={i} role="listitem">
                  <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
                  <TraceCollapsibleContent className="agent-trace-wrap">{step.detail}</TraceCollapsibleContent>
                </TraceCollapsible>
              ) : (
                <div key={i}>{line}</div>
              );
            })}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

/** A list of short items under one open line (acceptance criteria, open questions). */
export function TraceList({ title, items, icon }: { title: string; items: string[]; icon: string }) {
  if (!items.length) return null;
  return (
    <Trace className="agent-trace">
      <TraceCollapsible defaultOpen>
        <TraceCollapsibleTrigger>
          <TraceLine>
            <TraceIcon>
              <Ic n={icon} />
            </TraceIcon>
            <TraceTitle>{title}</TraceTitle>
            <TraceDescription>{items.length}</TraceDescription>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace role="list" aria-label={title}>
            {items.map((item, i) => (
              <TraceLine key={i} role="listitem">
                <TraceIcon>
                  <Ic n="circle" />
                </TraceIcon>
                <TraceTitle className="agent-trace-wrap">{item}</TraceTitle>
              </TraceLine>
            ))}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

export interface QueueEntry {
  id: string;
  kind: "queue" | "steer";
  message: string;
  status: string;
  said: string;
  error?: string | null;
  onCancel?: () => void;
  cancelling?: boolean;
}

/** Queue: what you've sent while Nova works, under "2 waiting": each message, how far it got, and Cancel while it
 *  hasn't gone. */
export function Queue({ entries }: { entries: QueueEntry[] }) {
  if (!entries.length) return null;
  const steering = entries.filter((e) => e.kind === "steer").length;
  const title = [entries.length - steering && `${entries.length - steering} queued`, steering && `${steering} steering`].filter(Boolean).join(", ");
  return (
    <Trace className="agent-trace agent-queue">
      <TraceCollapsible defaultOpen>
        <TraceCollapsibleTrigger>
          <TraceLine>
            <TraceIcon>
              <Ic n="queue" />
            </TraceIcon>
            <TraceTitle>{title}</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <div className="agent-queue-list" role="list" aria-label="Queued and steering">
            {entries.map((e) => {
              const status: TraceStatus | undefined = e.status === "rejected" ? "error" : e.status === "sending" ? "running" : undefined;
              return (
                <div key={e.id} role="listitem" className={`chat-input-state ${e.status}`}>
                  <TraceLine status={status}>
                    <TraceIcon>
                      {status === "running" ? (
                        <Spinner />
                      ) : (
                        <Ic n={e.status === "rejected" ? "warning-circle" : e.kind === "steer" ? "steering-wheel" : "circle"} />
                      )}
                    </TraceIcon>
                    <TraceTitle className="chat-input-message" title={e.message}>
                      {e.message}
                    </TraceTitle>
                    <TraceDescription className="chat-input-result" role="status">
                      {e.kind === "queue" ? "Queued" : "Steering"} · {e.said}
                    </TraceDescription>
                  </TraceLine>
                  {e.onCancel && (
                    <button className="btn btn-xs btn-ghost" disabled={e.cancelling} onClick={e.onCancel}>
                      Cancel
                    </button>
                  )}
                  {e.error && <span className="chat-input-error">{e.error}</span>}
                </div>
              );
            })}
          </div>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

/** Confirmation: an agent's change waiting for a person, as one row: what it does, then the decision. */
export function Confirmation({ icon, title, description, children }: { icon: string; title: string; description: string; children: ReactNode }) {
  return (
    <Item variant="muted" size="xs" className="agent-confirm">
      <ItemMedia variant="icon">
        <Ic n={icon} />
      </ItemMedia>
      <ItemContent>
        <ItemTitle>{title}</ItemTitle>
        <ItemDescription>{description}</ItemDescription>
      </ItemContent>
      <ItemActions>{children}</ItemActions>
    </Item>
  );
}

/** Checkpoint: a line after a turn that left a commit, naming it, with what can be done from there. */
export function Checkpoint({ label, children }: { label: ReactNode; children?: ReactNode }) {
  return (
    <Marker variant="separator" className="agent-checkpoint" role="separator" aria-label="Checkpoint">
      <MarkerContent className="inline-flex items-center gap-2">
        <MarkerIcon>
          <Ic n="git-commit" />
        </MarkerIcon>
        {label}
        {children}
      </MarkerContent>
    </Marker>
  );
}

export interface Usage {
  input?: number | null;
  cached?: number | null;
  output?: number | null;
  calls?: number | null;
  cost?: number | null;
  complete?: boolean | null;
  model?: string | null;
}

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k` : String(n));

/** Context: a reply's tokens as a chip; hovering it breaks them down (read, of which cached, written, model calls,
 *  cost). Usage a provider didn't report is said to be incomplete rather than shown as nothing. */
export function ContextUsage({ usage }: { usage: Usage }) {
  const input = usage.input ?? 0;
  const output = usage.output ?? 0;
  const total = input + output;
  if (!total) return null;
  const share = total ? Math.round((input / total) * 100) : 0;
  return (
    <HoverCard>
      <HoverCardTrigger asChild>
        <button type="button" className="agent-usage" aria-label={`${k(total)} tokens: details`}>
          <Ic n="chart-donut" s={12} />
          {k(total)} tokens
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="agent-usage-card" align="start">
        <div className="agent-usage-h">
          <b>Tokens</b>
          <span className="mono">{total.toLocaleString()}</span>
        </div>
        <div className="agent-usage-bar" role="img" aria-label={`${share}% read, ${100 - share}% written`}>
          <span style={{ width: `${share}%` }} />
        </div>
        <dl className="agent-usage-kv">
          <dt>Read</dt>
          <dd className="mono">{input.toLocaleString()}</dd>
          {usage.cached ? (
            <>
              <dt>Of which cached</dt>
              <dd className="mono">{usage.cached.toLocaleString()}</dd>
            </>
          ) : null}
          <dt>Written</dt>
          <dd className="mono">{output.toLocaleString()}</dd>
          {usage.calls ? (
            <>
              <dt>Model calls</dt>
              <dd className="mono">{usage.calls}</dd>
            </>
          ) : null}
          {usage.cost != null ? (
            <>
              <dt>Cost</dt>
              <dd className="mono">${usage.cost.toFixed(usage.cost < 1 ? 3 : 2)}</dd>
            </>
          ) : null}
        </dl>
        {usage.model && <p className="agent-usage-note">{usage.model} · on your key</p>}
        {usage.complete === false && <p className="agent-usage-note">The provider didn't report all of it: the real use is higher.</p>}
      </HoverCardContent>
    </HoverCard>
  );
}
