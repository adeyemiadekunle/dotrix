// Agent actions for live workspaces; demo-only canned interactions delegate to ../demo/agents.
import { D, demoRuntime, me, mutate } from "../data/store";
import type { ChatMessage, CodingSession, ProposedChange, Thread } from "../data/types";
import { runContinued } from "../data/account";
import { isLive, live } from "../data/live";
import { toast } from "../ui/toast";

export function threadOf(changeId: string): { th: Thread; msg: ChatMessage; ch: ProposedChange } | null {
  for (const th of D().threads)
    for (const msg of th.messages) {
      const ch = msg.changes?.find((c) => c.id === changeId);
      if (ch) return { th, msg, ch };
    }
  return null;
}

/** The autonomy action each kind of change takes, and how to say it. */
export const ACTION_OF: Partial<Record<ProposedChange["kind"], [string, string]>> = {
  write_file: ["knowledge.write", "write documents"],
  create_issue: ["issues.create", "open issues"],
  update_issue: ["issues.update", "edit issues"],
  comment: ["issues.comment", "comment on issues"],
};

/** Who may "Always allow this": owners. */
export const canAlwaysAllow = () => (isLive() ? live.ws?.role === "owner" : me()?.role === "Owner");

export function decideChange(changeId: string, approve: boolean, reason = "") {
  if (!isLive()) demoRuntime()?.decideChange(changeId, approve, reason);
}

export function alwaysAllow(changeId: string) {
  if (!isLive()) demoRuntime()?.alwaysAllow(changeId);
}

export function answerCheckpoint(changeId: string, answer: "continue" | "steer" | "stop", note = "") {
  if (!isLive()) demoRuntime()?.answerCheckpoint(changeId, answer, note);
}

export function startCoding(t: { id: string; key: string; title: string; project: string }, tool: CodingSession["tool"], note = ""): string | null {
  if (isLive()) return null;
  return demoRuntime()?.startCoding(t, tool, note) ?? null;
}

export function decideCoding(cs: CodingSession, approve: boolean, reason = "") {
  if (!isLive()) demoRuntime()?.decideCoding(cs, approve, reason);
}

/** Continue a run that stopped at its model's limit: now, or once the limit resets. */
export function continueLimited(at: { thread?: string; project?: string; run?: string; notif?: string }, whenReset: boolean) {
  const done = () => {
    if (at.notif) mutate(() => D().notifs.forEach((n) => n.id === at.notif && (n.read = true)));
  };
  if (isLive()) {
    if (!at.project || !at.run) return;
    void runContinued(at.project, at.run, whenReset)
      .then((r) => {
        done();
        toast(
          r.continue_at_reset
            ? "It'll continue when the limit resets"
            : r.status === "failed"
              ? "Still at the limit; try again shortly"
              : "Continuing where it stopped",
        );
      })
      .catch((e: unknown) => toast(e instanceof Error && e.message ? e.message : "It couldn't continue", { kind: "err" }));
    return;
  }
  demoRuntime()?.continueLimited(at, whenReset, done);
}

const toasted = new Set<string>();
/** A real workspace opening with a run stopped at its model's limit (the last 12 hours, unread):
 * a toast with Continue, once per session. */
export function limitToasts() {
  const since = Date.now() - 12 * 3_600_000;
  for (const n of D().notifs) {
    if (n.type !== "limit" || n.read || n.at < since || toasted.has(n.id)) continue;
    toasted.add(n.id);
    const agent = D().agents.find((a) => a.handle === n.by);
    toast(`${agent?.name ?? "An agent"} stopped at its model's limit: ${n.text}`, {
      action: "Continue",
      onAction: () => continueLimited({ thread: n.thread, project: n.project, run: n.run, notif: n.id }, false),
      ms: 10_000,
    });
  }
}
