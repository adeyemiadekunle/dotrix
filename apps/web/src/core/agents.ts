// dotrix's agent actions on the seeded data: deciding an agent's proposed changes, answering a
// checkpoint, chatting (a canned reply after a short "working" pause), and coding sessions.
// When the API is wired, each becomes a call (runs, approvals, coding) and the replies stream.
import { D, S, me, mutate, proj, render, task, who } from "../data/store";
import type { ChatMessage, CodingSession, ProposedChange, Thread } from "../data/types";
import { runContinued } from "../data/account";
import { isLive, live } from "../data/live";
import { toast } from "../ui/toast";
import { createTask } from "./actions";
import { go } from "./nav";
import { dOff, uid } from "./utils";

export function threadOf(changeId: string): { th: Thread; msg: ChatMessage; ch: ProposedChange } | null {
  for (const th of D().threads)
    for (const msg of th.messages) {
      const ch = msg.changes?.find((c) => c.id === changeId);
      if (ch) return { th, msg, ch };
    }
  return null;
}

/** The agents' items about a thread are settled once nothing in it waits. */
function settleNotifs(th: Thread) {
  const waiting = th.messages.some((m) => m.changes?.some((c) => c.status === "pending"));
  if (!waiting) D().notifs.forEach((n) => n.thread === th.id && (n.type === "approval" || n.type === "checkpoint") && (n.read = true));
}

/** Text after a unified diff is applied: context and added lines. */
const applied = (diff: string) =>
  diff
    .split("\n")
    .filter((l) => !l.startsWith("-"))
    .map((l) => l.slice(1))
    .join("\n");

export function decideChange(changeId: string, approve: boolean, reason = "") {
  const f = threadOf(changeId);
  if (!f || f.ch.status !== "pending") return;
  const { th, msg, ch } = f;
  mutate(() => {
    ch.status = approve ? "approved" : "rejected";
    ch.decidedBy = D().me;
    ch.reason = reason || undefined;
    const pid = th.project ?? th.projects?.[0] ?? null;
    if (approve && ch.kind === "write_file" && ch.diff && pid) {
      const kf = D().knowledge.find((k) => k.project === pid && k.path === ch.title);
      const content = applied(ch.diff);
      if (kf) Object.assign(kf, { content, version: kf.version + 1, by: msg.by, at: Date.now() });
      else D().knowledge.push({ path: ch.title, project: pid, content, version: 1, by: msg.by, at: Date.now() });
    }
    if (approve && ch.kind === "create_issue" && pid) {
      const fl = ch.fields ?? {};
      const assignee = D().members.find((m) => m.name === fl.Assignee)?.id ?? null;
      const t = createTask({
        project: pid,
        title: ch.title,
        type: (fl.Type?.toLowerCase() as never) || "task",
        priority: (fl.Priority?.toLowerCase() as never) || "none",
        assignee,
        due: fl.Due ? dOff(3) : null,
      });
      D().activity[0]!.by = msg.by; // created by the agent, on your approval
      ch.fields = { ...fl, Key: t.key };
    }
    D().audit.unshift({ id: uid("au"), at: Date.now(), by: D().me, action: approve ? "approval.approved" : "approval.rejected", target: ch.title, project: pid ?? undefined });
    if (pid) D().activity.unshift({ id: uid("a"), by: D().me, verb: approve ? "approved" : "rejected", task: null, project: pid, at: Date.now(), extra: `${who(msg.by)?.name}'s change to ${ch.title}` });
    settleNotifs(th);
  });
  toast(approve ? `Approved: ${ch.title}` : `Rejected: ${ch.title}`, { ms: 2200 });
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

/** "Always allow this": approve the change, and let its agent make that kind of change without
 * asking from now on (a new version of its contract; the API's `.../always-allow`). */
export function alwaysAllow(changeId: string) {
  const f = threadOf(changeId);
  const act = f && ACTION_OF[f.ch.kind];
  const agent = f && D().agents.find((a) => a.handle === f.msg.by);
  if (!f || !act || !agent) return;
  mutate(() => {
    agent.allows = [...new Set([...(agent.allows ?? []), act[0]])];
    agent.customised = agent.builtIn || undefined;
    D().audit.unshift({ id: uid("au"), at: Date.now(), by: D().me, action: "agent.updated", target: `${agent.name}: always ${act[1]}` });
  });
  decideChange(changeId, true);
  toast(`${agent.name} may now ${act[1]} without asking`, { action: "Settings", onAction: () => ((S.ui.agentSel = agent.handle), go("settings", { sec: "agents" })) });
}

export function decideAll(msg: ChatMessage, approve: boolean) {
  msg.changes?.filter((c) => c.status === "pending" && c.kind !== "checkpoint").forEach((c) => decideChange(c.id, approve));
}

/** A checkpoint: continue, change the plan (steer), or stop. */
export function answerCheckpoint(changeId: string, answer: "continue" | "steer" | "stop", note = "") {
  const f = threadOf(changeId);
  if (!f || f.ch.status !== "pending") return;
  const { th, msg, ch } = f;
  mutate(() => {
    ch.status = answer === "stop" ? "rejected" : "approved";
    ch.decidedBy = D().me;
    ch.reason = note || undefined;
    if (answer === "steer") th.messages.push({ id: uid("cm"), role: "user", by: D().me, at: Date.now(), text: `Change the plan: ${note}` });
    settleNotifs(th);
  });
  const reply =
    answer === "stop"
      ? "Stopped. Here's what I found so far: the app reads issues, comments, and attachments offline, and writes status changes and comments."
      : answer === "steer"
        ? `Updated the plan with your changes. Working through it now:\n\n${(ch.plan ?? []).map((s, i) => `${i + 1}. ${s}`).join("\n")}\n\n*(${note})*`
        : "Continuing with the plan. **Recommendation:** a server-side queue with last-write-wins per field; CRDTs are more than the app needs. I've drafted an ADR you can review below.";
  agentReply(th, msg.by, reply, answer === "continue" ? ["Read architecture/overview.md", "Compared 3 approaches"] : []);
}

/** The agent answers after a short pause (seeded: canned, by intent). */
export function agentReply(th: Thread, by: string, text: string, activity: string[] = [], changes?: ProposedChange[]) {
  S.ui.chatBusy = th.id;
  render();
  setTimeout(() => {
    mutate(() => {
      th.messages.push({ id: uid("cm"), role: "agent", by, at: Date.now(), text, activity, changes, tokens: 6000 + Math.round(Math.random() * 9000) });
      th.at = Date.now();
    });
    S.ui.chatBusy = null;
    render();
  }, 1100);
}

function cannedAnswer(th: Thread, q: string): { text: string; activity: string[]; changes?: ProposedChange[] } {
  const p = proj(th.project);
  const name = p?.name ?? "your projects";
  const ql = q.toLowerCase();
  const open = D().tasks.filter((t) => (!p || t.project === p.id) && t.status !== "done" && !t.archived);
  if (/summar|status|what changed|update/.test(ql))
    return {
      activity: ["Read current-state.md", "Listed the board"],
      text: `**${name}**: ${open.length} open issues, ${open.filter((t) => t.status === "progress").length} in progress, ${open.filter((t) => t.status === "blocked").length} blocked.\n\nNext up: ${open
        .slice(0, 3)
        .map((t) => `**${t.key}** ${t.title}`)
        .join(", ")}.`,
    };
  if (/stor|issue|ticket|break.*down/.test(ql) && p)
    return {
      activity: ["Read requirements/", "Searched the board for duplicates"],
      text: "I'd add one story for this. It waits for your approval:",
      changes: [{ id: uid("pc"), kind: "create_issue", title: q.replace(/^.*?(add|create|write)\s+/i, "").slice(0, 80) || "New story", fields: { Type: "Story", Priority: "Medium" }, status: "pending" }],
    };
  return {
    activity: ["Read project.md", "Searched the project's documents"],
    text: `Here's what I found in ${name}'s documents and board. ${open.length ? `The most urgent open issue is **${open[0]!.key}** ${open[0]!.title}.` : "Nothing is open."} Ask me to turn this into issues or a document when you're ready.`,
  };
}

/** Chat and coding run on the API in the next step; a real workspace says so instead of a canned reply. */
export function agentsNotWired(): boolean {
  if (!isLive()) return false;
  toast("Chat with the agents comes to your workspace in the next update. Try it in the demo workspace.", { kind: "info", ms: 5000 });
  return true;
}

export function sendChat(th: Thread, text: string, agent: string) {
  const q = text.trim();
  if (!q || agentsNotWired()) return;
  mutate(() => {
    th.messages.push({ id: uid("cm"), role: "user", by: D().me, at: Date.now(), text: q });
    th.agent = agent;
    th.at = Date.now();
  });
  const a = cannedAnswer(th, q);
  agentReply(th, agent, a.text, a.activity, a.changes);
}

export function newThread(project: string | null, agent: string, model: string, first: string, projects?: string[]): Thread | null {
  if (agentsNotWired()) return null;
  const title = first.replace(/^(hi|hello|hey)[,!.\s]+/i, "").replace(/^(can|could) you\s+|^please\s+/i, "").split(/[.?!\n]/)[0]!.split(" ").slice(0, 7).join(" ");
  const th: Thread = { id: uid("th"), project, projects, title: title[0]?.toUpperCase() + title.slice(1) || "New chat", by: D().me, agent, model, at: Date.now(), messages: [] };
  mutate(() => D().threads.unshift(th));
  sendChat(th, first, agent);
  return th;
}

/* ---------- coding sessions ---------- */
export function decideCoding(cs: CodingSession, approve: boolean, reason = "") {
  if (cs.status !== "awaiting_approval") return;
  mutate(() => {
    cs.status = approve ? "running" : "rejected";
    if (approve) cs.branch = `dotrix/${task(cs.task)!.key.toLowerCase()}-${task(cs.task)!.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 30)}`;
    if (approve) cs.turns.at(-1)!.events.push("Checked out the default branch", "Reading the code");
    else cs.turns.at(-1)!.summary = reason ? `Rejected: ${reason}` : "Rejected";
    D().notifs.forEach((n) => n.task === cs.task && n.type === "approval" && (n.read = true));
    D().audit.unshift({ id: uid("au"), at: Date.now(), by: D().me, action: approve ? "coding.approved" : "coding.rejected", target: task(cs.task)!.key, project: cs.project });
  });
  toast(approve ? `${cs.tool === "codex" ? "Codex" : "Claude Code"} is coding ${task(cs.task)!.key}` : "Coding rejected", { ms: 2200 });
}
export function stopCoding(cs: CodingSession) {
  mutate(() => {
    cs.status = "stopped";
    cs.turns.at(-1)!.summary = "Stopped before it finished.";
  });
}
export function followUp(cs: CodingSession, ask: string) {
  if (!ask.trim()) return;
  mutate(() => {
    cs.turns.push({ at: Date.now(), ask: ask.trim(), events: [] });
    cs.status = "awaiting_approval";
    cs.at = Date.now();
  });
}


/* ---------- a run stopped at its model's limit ---------- */

/** Where a conversation stopped at its model's limit (the seeded data's message for it). */
function limitedMessage(threadId: string | undefined): { th: Thread; msg: ChatMessage } | null {
  const th = D().threads.find((t) => t.id === threadId);
  const msg = th?.messages.findLast((m) => m.limit && !m.limit.continued);
  return th && msg ? { th, msg } : null;
}

/** Continue a run that stopped at its model's limit: now, or once the limit resets. In a real
 * workspace it's the API's `.../continue`; on the seeded data it carries on here. */
export function continueLimited(at: { thread?: string; project?: string; run?: string; notif?: string }, whenReset: boolean) {
  const done = () => {
    if (at.notif) mutate(() => D().notifs.forEach((n) => n.id === at.notif && (n.read = true)));
  };
  if (isLive()) {
    if (!at.project || !at.run) return;
    void runContinued(at.project, at.run, whenReset)
      .then((r) => {
        done();
        toast(r.continue_at_reset ? "It'll continue when the limit resets" : r.status === "failed" ? "Still at the limit; try again shortly" : "Continuing where it stopped");
      })
      .catch((e: unknown) => toast(e instanceof Error && e.message ? e.message : "It couldn't continue", { kind: "err" }));
    return;
  }
  const found = limitedMessage(at.thread);
  if (!found) return done();
  const { th, msg } = found;
  if (whenReset) {
    mutate(() => (msg.limit!.whenReset = true));
    done();
    return toast("It'll continue when the limit resets");
  }
  mutate(() => {
    msg.limit!.continued = true;
    th.messages.push({
      id: uid("cm"),
      role: "agent",
      by: msg.by,
      at: Date.now(),
      activity: ["Picked up where it stopped", "Read requirements/navigation.md"],
      text: "Picking up where I stopped: two things block the handoff. **The navigation spec** waits for your approval, and **WEB-139** (the hero component) hasn't started.",
    });
  });
  done();
  toast("Continuing where it stopped");
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
