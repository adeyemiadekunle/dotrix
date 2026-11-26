// Demo-only canned agent interactions (isolated from live API runs).
import { createTask } from "../core/actions";
import { ACTION_OF, threadOf } from "../core/agents";
import { go } from "../core/nav";
import { dOff, uid } from "../core/utils";
import { D, S, mutate, proj, render, task, toolName, who } from "../data/store";
import type { ChatMessage, CodingSession, ProposedChange, Thread } from "../data/types";
import { toast } from "../ui/toast";

function settleNotifs(th: Thread) {
  const waiting = th.messages.some((m) => m.changes?.some((c) => c.status === "pending"));
  if (!waiting) D().notifs.forEach((n) => n.thread === th.id && (n.type === "approval" || n.type === "checkpoint") && (n.read = true));
}

const applied = (diff: string) =>
  diff
    .split("\n")
    .filter((l) => !l.startsWith("-"))
    .map((l) => l.slice(1))
    .join("\n");

export function demoDecideChange(changeId: string, approve: boolean, reason = "") {
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
      D().activity[0]!.by = msg.by;
      ch.fields = { ...fl, Key: t.key };
    }
    D().audit.unshift({
      id: uid("au"),
      at: Date.now(),
      by: D().me,
      action: approve ? "approval.approved" : "approval.rejected",
      target: ch.title,
      project: pid ?? undefined,
    });
    if (pid)
      D().activity.unshift({
        id: uid("a"),
        by: D().me,
        verb: approve ? "approved" : "rejected",
        task: null,
        project: pid,
        at: Date.now(),
        extra: `${who(msg.by)?.name}'s change to ${ch.title}`,
      });
    settleNotifs(th);
  });
  toast(approve ? `Approved: ${ch.title}` : `Rejected: ${ch.title}`, { ms: 2200 });
}

export function demoAlwaysAllow(changeId: string) {
  const f = threadOf(changeId);
  const act = f && ACTION_OF[f.ch.kind];
  const agent = f && D().agents.find((a) => a.handle === f.msg.by);
  if (!f || !act || !agent) return;
  mutate(() => {
    agent.allows = [...new Set([...(agent.allows ?? []), act[0]])];
    agent.customised = agent.builtIn || undefined;
    D().audit.unshift({ id: uid("au"), at: Date.now(), by: D().me, action: "agent.updated", target: `${agent.name}: always ${act[1]}` });
  });
  demoDecideChange(changeId, true);
  toast(`${agent.name} may now ${act[1]} without asking`, {
    action: "Settings",
    onAction: () => ((S.ui.agentSel = agent.handle), go("settings", { sec: "agents" })),
  });
}

function agentReply(th: Thread, by: string, text: string, activity: string[] = [], changes?: ProposedChange[]) {
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

export function demoAnswerCheckpoint(changeId: string, answer: "continue" | "steer" | "stop", note = "") {
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

function repoName(url: string | undefined): string | undefined {
  if (!url) return undefined;
  const m = url.match(/github\.com[/:]([^/]+\/[^/.]+)/);
  return m ? m[1] : url;
}

export function demoStartCoding(t: { id: string; key: string; title: string; project: string }, tool: CodingSession["tool"], note = ""): string | null {
  const id = uid("cs");
  const ask = note.trim() || t.title;
  mutate(() => {
    const repo = repoName(proj(t.project)?.repo);
    D().coding.unshift({
      id,
      project: t.project,
      task: t.id,
      tool,
      status: "awaiting_approval",
      by: D().me,
      at: Date.now(),
      ...(repo ? { repo } : {}),
      turns: [{ at: Date.now(), ask, events: [] }],
    });
    D().notifs.unshift({
      id: uid("n"),
      type: "approval",
      by: `agent:${tool}`,
      project: t.project,
      task: t.id,
      text: "is waiting to start coding",
      snippet: `${t.key} ${t.title}`,
      at: Date.now(),
      read: false,
    });
  });
  return id;
}

export function demoDecideCoding(cs: CodingSession, approve: boolean, reason = "") {
  if (cs.status !== "awaiting_approval") return;
  mutate(() => {
    cs.status = approve ? "running" : "rejected";
    if (approve)
      cs.branch = `dotrix/${task(cs.task)!.key.toLowerCase()}-${task(cs.task)!
        .title.toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .slice(0, 30)}`;
    if (approve) cs.turns.at(-1)!.events.push("Checked out the default branch", "Reading the code");
    else cs.turns.at(-1)!.summary = reason ? `Rejected: ${reason}` : "Rejected";
    D().notifs.forEach((n) => n.task === cs.task && n.type === "approval" && (n.read = true));
    D().audit.unshift({
      id: uid("au"),
      at: Date.now(),
      by: D().me,
      action: approve ? "coding.approved" : "coding.rejected",
      target: task(cs.task)!.key,
      project: cs.project,
    });
  });
  toast(approve ? `${toolName(cs.tool)} is coding ${task(cs.task)!.key}` : "Coding rejected", { ms: 2200 });
}

function limitedMessage(threadId: string | undefined): { th: Thread; msg: ChatMessage } | null {
  const th = D().threads.find((t) => t.id === threadId);
  const msg = th?.messages.findLast((m) => m.limit && !m.limit.continued);
  return th && msg ? { th, msg } : null;
}

export function demoContinueLimited(at: { thread?: string; notif?: string }, whenReset: boolean, markNotifRead: () => void) {
  const found = limitedMessage(at.thread);
  if (!found) return markNotifRead();
  const { th, msg } = found;
  if (whenReset) {
    mutate(() => (msg.limit!.whenReset = true));
    markNotifRead();
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
  markNotifRead();
  toast("Continuing where it stopped");
}
