// What each agent is doing right now, read from the store: answering in a conversation, waiting
// for someone to approve its change or steer its plan, a coding tool running or waiting, or idle.
// One place for the agents panel, the corner notices, and the faces' moods.
import { decideChange, decideCoding } from "./agents";
import { D, S, task } from "../data/store";
import { CODING_TOOLS } from "../data/seed-dotrix";
import type { ChatMessage, CodingSession, ProposedChange, Thread } from "../data/types";
import type { Mood } from "../ui/face";

export type State = "working" | "needs" | "blocked" | "idle";
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

const toolOf = (cs: CodingSession) => `agent:${cs.tool}`;

export function presence(): Presence[] {
  const waiting = waitingChanges();
  const notifs = pendingNotifs();
  const busy = S.ui.chatBusy ? D().threads.find((t) => t.id === S.ui.chatBusy) : undefined;
  const agents: Presence[] = D().agents.map((a) => {
    const base = { id: a.handle, name: a.name, role: a.role, c: a.c };
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
    return { ...base, state: "idle", mood: "idle", now: READY[a.handle] ?? (a.desc || "Ready") };
  });
  // Coding tools appear while they have a session to show.
  const tools: Presence[] = [];
  for (const t of CODING_TOOLS) {
    const cs = D().coding.find((x) => toolOf(x) === t.id && ["running", "queued", "awaiting_approval", "failed"].includes(x.status));
    if (!cs) continue;
    const key = task(cs.task)?.key ?? "";
    const base = { id: t.id, name: t.name, role: "Coding", c: t.c, session: cs.id };
    if (cs.status === "awaiting_approval")
      tools.push({ ...base, state: "needs", mood: "needs", now: `Waiting for approval to code ${key}`, approve: () => decideCoding(cs, true) });
    else if (cs.status === "failed") tools.push({ ...base, state: "blocked", mood: "blocked", now: `Couldn't finish ${key}` });
    else tools.push({ ...base, state: "working", mood: "working", now: cs.status === "queued" ? `Queued to code ${key}` : `Coding ${key}` });
  }
  return [...agents, ...tools];
}

/** The mood a face shows for an agent handle (or coding tool) anywhere in the app. */
export function moodOf(id: string): Mood {
  return presence().find((p) => p.id === id)?.mood ?? "idle";
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
