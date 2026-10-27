// What each agent is doing right now, read from the store: answering in a conversation, waiting
// for someone to approve its change or steer its plan, a coding tool running or waiting, or idle.
// One place for the agents panel, the corner notices, and the faces' moods.
import { decideChange, decideCoding } from "./agents";
import { D, S, task } from "../data/store";
import { CODING_AGENT, CODING_TOOLS } from "../data/seed-dotrix";
import type { ChatMessage, ProposedChange, Thread } from "../data/types";
import type { Mood } from "../ui/face";
import type { AgentActivity } from "@/lib/team";

type State = "working" | "needs" | "blocked" | "idle";
export interface Presence {
  id: string; // an agent handle, or a coding tool ("agent:claude-code")
  name: string;
  role: string;
  c: string;
  state: State;
  mood: Mood;
  /** one line: what it's doing, or what it's ready for */
  now: string;
  /** where "now" happens, to open it */
  thread?: string;
  session?: string;
  project?: string;
  review?: boolean;
  /** approve what it waits for, when that's one change */
  approve?: () => void;
}

const READY: Record<string, string> = {
  auto: "Ready to plan",
  product: "Ready to write requirements",
  architecture: "Ready to weigh a change",
  research: "Ready for research",
  reviewer: "Ready to review",
  documentation: "Ready to update documents",
};

/** A change an agent proposed that still waits for a person, newest first. */
export interface Waiting {
  agent: string;
  th: Thread;
  msg: ChatMessage;
  ch: ProposedChange;
}
export function waitingChanges(): Waiting[] {
  const out: Waiting[] = [];
  for (const th of D().threads)
    for (const msg of th.messages)
      if (msg.role === "agent") for (const ch of msg.changes ?? []) if (ch.status === "pending") out.push({ agent: msg.by, th, msg, ch });
  return out.sort((a, b) => b.msg.at - a.msg.at);
}

/** Approvals and checkpoints from the API's notifications (a real workspace has no seeded threads). */
const pendingNotifs = () => D().notifs.filter((n) => (n.type === "approval" || n.type === "checkpoint") && !n.read && n.by);

export function presence(activity: AgentActivity[] = []): Presence[] {
  const waiting = waitingChanges();
  const notifs = pendingNotifs();
  const busy = S.ui.chatBusy ? D().threads.find((t) => t.id === S.ui.chatBusy) : undefined;
  const agents: Presence[] = D().agents.map((a) => {
    const base = { id: a.handle, name: a.name, role: a.role, c: a.c, review: a.handle === "reviewer" };
    const liveTask = activity.find(
      (item) =>
        (item.agent === a.handle || (item.agent === "project-manager" && a.handle === "auto")) &&
        ["queued", "running", "waiting_children", "waiting_dependency", "awaiting_approval", "failed", "blocked"].includes(item.status),
    );
    if (liveTask) {
      const state: State = liveTask.status === "awaiting_approval" ? "needs" : ["failed", "blocked"].includes(liveTask.status) ? "blocked" : "working";
      return {
        ...base,
        state,
        mood: state,
        now: `${liveTask.status.replaceAll("_", " ")} · ${liveTask.title}`,
        thread: liveTask.thread_id ?? undefined,
        project: liveTask.project_key,
        review: a.handle === "reviewer",
      };
    }
    if (busy && busy.agent === a.handle) return { ...base, state: "working", mood: "working", now: `Answering in “${busy.title}”`, thread: busy.id };
    const w = waiting.find((x) => x.agent === a.handle);
    if (w) {
      const steer = w.ch.kind === "checkpoint";
      const others = waiting.filter((x) => x.msg === w.msg).length;
      return {
        ...base,
        state: "needs",
        mood: "needs",
        now: steer
          ? `Waiting for you to steer · ${w.ch.title}`
          : others > 1
            ? `Waiting for approval · ${others} changes`
            : `Waiting for approval · ${w.ch.title}`,
        thread: w.th.id,
        approve: !steer && others === 1 ? () => decideChange(w.ch.id, true) : undefined,
      };
    }
    const n = notifs.find((x) => x.by === a.handle);
    if (n) return { ...base, state: "needs", mood: "needs", now: n.text };
    const recentReview = a.handle === "reviewer" ? activity.find((item) => item.agent === "reviewer") : undefined;
    return {
      ...base,
      state: "idle",
      mood: "idle",
      now: READY[a.handle] ?? (a.desc || "Ready"),
      thread: recentReview?.thread_id ?? undefined,
      project: recentReview?.project_key,
    };
  });
  // Kai, the coding agent, appears while it has a session to show: one row, whichever engine codes,
  // for the session that matters most (waiting on you, then working, then one it couldn't finish).
  const tools: Presence[] = [];
  const rank = {
    awaiting_approval: 0,
    changes_ready: 0,
    recovery_required: 0,
    running: 1,
    queued: 1,
    failed: 2,
    pr_opened: 3,
    no_changes: 3,
    stopped: 3,
    rejected: 3,
  } as Record<string, number>;
  const cs = D()
    .coding.filter((x) => x.status in rank && !x.archived && x.state !== "closed")
    .sort((a, b) => rank[a.status]! - rank[b.status]! || b.at - a.at)[0];
  if (cs) {
    const key = task(cs.task)?.key ?? "";
    const base = { id: CODING_AGENT.id, name: CODING_AGENT.name, role: "Coding", c: CODING_AGENT.c, session: cs.id };
    if (cs.status === "awaiting_approval")
      tools.push({ ...base, state: "needs", mood: "needs", now: `Waiting for approval to code ${key}`, approve: () => decideCoding(cs, true) });
    else if (cs.status === "changes_ready") tools.push({ ...base, state: "needs", mood: "needs", now: `Changes ready for acceptance · ${key}` });
    else if (cs.status === "recovery_required") tools.push({ ...base, state: "blocked", mood: "blocked", now: `Needs recovery · ${key}` });
    else if (cs.status === "failed") tools.push({ ...base, state: "blocked", mood: "blocked", now: `Couldn't finish ${key}` });
    else if (cs.status === "running" || cs.status === "queued")
      tools.push({ ...base, state: "working", mood: "working", now: cs.status === "queued" ? `Queued to code ${key}` : `Coding ${key}` });
    else tools.push({ ...base, state: "idle", mood: "idle", now: `Session ${cs.title || key} · ${cs.status.replaceAll("_", " ")}` });
  } else {
    const task = activity.find((item) => item.agent === "coding-agent");
    const state: State = !task
      ? "idle"
      : ["awaiting_approval", "changes_ready"].includes(task.status)
        ? "needs"
        : ["recovery_required", "failed"].includes(task.status)
          ? "blocked"
          : ["running", "queued"].includes(task.status)
            ? "working"
            : "idle";
    tools.push({
      id: CODING_AGENT.id,
      name: CODING_AGENT.name,
      role: "Coding",
      c: CODING_AGENT.c,
      state,
      mood: state,
      session: task?.session_id ?? undefined,
      now: task ? `${task.status.replaceAll("_", " ")} · ${task.title}` : "Ready for instructed work in Build mode",
    });
  }
  return [...agents, ...tools];
}

/** The mood a face shows for an agent handle (or coding tool) anywhere in the app. */
export function moodOf(id: string): Mood {
  const who = CODING_TOOLS.some((c) => c.id === id) ? CODING_AGENT.id : id; // every engine's id is Kai
  return presence().find((p) => p.id === who)?.mood ?? "idle";
}

/** Today's agent work, for the panel's footer: replies and the tokens they used. */
export function today(): { replies: number; tokens: number } {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  let replies = 0;
  let tokens = 0;
  for (const th of D().threads)
    for (const m of th.messages)
      if (m.role === "agent" && m.at >= start.getTime()) {
        replies++;
        tokens += m.tokens ?? 0;
      }
  return { replies, tokens };
}
