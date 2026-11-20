import { Code as InlineCode } from "@dotrix/ui/astryx";
import { useState } from "react";

import { useCodingEvents, type CodingRun } from "@/lib/coding";
import type { Scope } from "@/lib/issues";
import { taskEvents, taskStatus } from "../core/backgroundTasks";
import { Ic } from "../core/icons";
import { ToolCalls } from "./AgentTrace";

/** Each turn owns its background history. Fetch the full event journal only when expanded. */
export function BackgroundTasks({ scope, run }: { scope: Scope | undefined; run: CodingRun }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const events = useCodingEvents(scope, run, open);
  const tasks = run.tasks ?? [];
  if (!tasks.length) return null;
  const active = run.status === "running";
  const working = tasks.filter((task) => ["running", "verifying"].includes(task.status)).length;
  const completed = tasks.filter((task) => task.status === "completed").length;
  return (
    <section className="background-tasks" aria-label={`Background tasks for turn ${run.turn}`}>
      <button className="background-tasks-heading" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Ic n={open ? "chevron-down" : "chevron-right"} s={14} />
        <Ic n={active && working ? "spinner-gap" : "flow-arrow"} cls={active && working ? "animate-spin" : undefined} s={16} />
        <b>Background tasks</b>
        <span className="faint">
          {completed}/{tasks.length} completed{active && working ? ` · ${working} working` : ""}
        </span>
      </button>
      {open && (
        <div className="background-task-list">
          {events.isError && (
            <p role="status">
              Activity could not be loaded.{" "}
              <button className="linkbtn" onClick={() => void events.refetch()}>
                Try again
              </button>
            </p>
          )}
          {tasks.map((task) => {
            const show = expanded.has(task.key);
            const activity = taskEvents(events.data ?? run.events, task.key);
            const status = taskStatus(task.status, run.status);
            const running = active && ["running", "verifying"].includes(task.status);
            return (
              <div className="background-task" key={task.key}>
                <button
                  className="background-task-heading"
                  aria-expanded={show}
                  onClick={() =>
                    setExpanded((previous) => {
                      const next = new Set(previous);
                      if (next.has(task.key)) next.delete(task.key);
                      else next.add(task.key);
                      return next;
                    })
                  }
                >
                  <Ic
                    n={running ? "spinner-gap" : task.status === "completed" ? "check-circle" : "flow-arrow"}
                    cls={running ? "animate-spin" : undefined}
                    s={16}
                  />
                  <span className="background-task-title">
                    <b>{task.key}</b>
                    <span className="faint">{status}</span>
                  </span>
                  <Ic n={show ? "chevron-down" : "chevron-right"} s={13} />
                </button>
                {show && (
                  <div className="background-task-body">
                    {(task.attempt ?? 0) > 1 && <p className="faint">Attempt {task.attempt}</p>}
                    <p className="mono background-task-paths">{(task.owned_paths ?? []).join(", ")}</p>
                    <p className="faint">
                      {running ? "Working in a separate sandbox. Stop the coding turn to stop all its tasks." : "Saved task activity and verification results."}
                    </p>
                    {events.isLoading && !activity.length ? (
                      <p role="status">Loading activity…</p>
                    ) : activity.length ? (
                      <ToolCalls events={activity} running={running} />
                    ) : (
                      <p className="faint">No activity recorded yet.</p>
                    )}
                    {(task.checks ?? []).map((check, index) => (
                      <details key={index} className="background-task-check">
                        <summary>
                          <InlineCode>{String(check.command ?? "Verification")}</InlineCode> ·{" "}
                          {check.exit_code === 0 ? "Passed" : check.exit_code == null ? "Unconfirmed" : `Failed (exit ${String(check.exit_code)})`}
                        </summary>
                        {check.expected != null && <p>Expected: {String(check.expected)}</p>}
                        {check.output != null && <pre className="mono">{String(check.output)}</pre>}
                      </details>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

type WorkState = "running" | "done" | "failed" | "stopped" | "ended";
const WORK_STATES: Record<WorkState, string> = {
  running: "Running",
  done: "Done",
  failed: "Failed",
  stopped: "Stopped",
  ended: "Ended",
};

/** Kai's background work in a turn, as Claude Code lists its background tasks: each command it left running and each
 *  of its workers (events `background-<state>`, `ref` naming it), at its latest state, running ones first. */
type Work = { ref: string; kind: "command" | "worker"; label: string; state: WorkState; output?: string };
/** Also what a command printed once it finished (`background-output`, recorded between turns as well). */
export function kaiBackground(events: CodingRun["events"]): Work[] {
  const latest = new Map<string, Work>();
  for (const e of events) {
    if (e.kind === "background-output" && e.ref) {
      const known = latest.get(e.ref);
      if (known) known.output = e.text;
      continue;
    }
    const state = e.kind.startsWith("background-") ? (e.kind.slice("background-".length) as WorkState) : null;
    if (!state || !(state in WORK_STATES) || !e.ref) continue;
    latest.set(e.ref, { ref: e.ref, kind: e.ref.startsWith("worker:") ? "worker" : "command", label: e.text, state, output: latest.get(e.ref)?.output });
  }
  return [...latest.values()].sort((a, b) => Number(b.state === "running") - Number(a.state === "running"));
}

export function KaiBackground({ run, kai }: { run: CodingRun; kai: string }) {
  const [open, setOpen] = useState(true);
  const work = kaiBackground(run.events);
  if (!work.length) return null;
  const running = work.filter((w) => w.state === "running").length;
  return (
    <section className="background-tasks" aria-label={`${kai}'s background tasks`}>
      <button className="background-tasks-heading" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Ic n={open ? "chevron-down" : "chevron-right"} s={14} />
        <Ic n={running ? "spinner-gap" : "flow-arrow"} cls={running ? "animate-spin" : undefined} s={16} />
        <b>Background tasks</b>
        <span className="faint">{running ? `${running} running` : `${work.length} finished`}</span>
      </button>
      {open && (
        <div className="background-task-list" role="list">
          {work.map((w) => (
            <div className="background-task" role="listitem" key={w.ref}>
              <span className="background-task-heading">
                <Ic
                  n={w.state === "running" ? "spinner-gap" : w.state === "done" ? "check-circle" : w.state === "failed" ? "warning-circle" : "stop-circle"}
                  cls={w.state === "running" ? "animate-spin" : undefined}
                  s={16}
                />
                <span className="background-task-title">
                  {w.kind === "command" ? <InlineCode>{w.label}</InlineCode> : <b>{w.label}</b>}
                  <span className="faint">
                    {w.kind === "worker" ? "Worker" : "Command"} · {WORK_STATES[w.state]}
                  </span>
                </span>
              </span>
              {w.output && w.state !== "running" && <pre className="background-task-output">{w.output}</pre>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
