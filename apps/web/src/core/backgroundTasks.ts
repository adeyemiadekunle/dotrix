import type { ToolEvent } from "../components/AgentTrace";

/** Worker prefixes are host-owned. Strip only the exact task prefix, preserving output refs. */
export function taskEvents<T extends ToolEvent>(events: T[], key: string): T[] {
  const prefix = `[${key}] `;
  return events.filter((event) => event.text.startsWith(prefix)).map((event) => ({ ...event, text: event.text.slice(prefix.length) }));
}

export function taskStatus(status: string, runStatus: string): string {
  if (["queued", "running", "verifying"].includes(status) && !["queued", "running"].includes(runStatus)) {
    return runStatus === "stopped" ? "Stopped" : "Interrupted";
  }
  return (
    (
      { queued: "Waiting", running: "Working", verifying: "Checking", verified: "Ready to integrate", completed: "Completed", blocked: "Blocked" } as Record<
        string,
        string
      >
    )[status] ?? status
  );
}
