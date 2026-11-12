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
                          <code>{String(check.command ?? "Verification")}</code> ·{" "}
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
