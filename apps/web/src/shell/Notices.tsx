import { ActionButton } from "@dotrix/ui/components/action-button";
// Corner notices (after Orbit's): only what needs a person, with the action in the notice. An
// agent's changes waiting for approval, a plan to steer, a coding turn waiting to start or with
// checked changes to push, or one that couldn't finish. On Home only (elsewhere they'd cover the
// page), and only while the agents panel is closed (it lists the same things); the newest two,
// bottom right; closing one keeps it closed for this session. An approval is decided in the notice
// itself (Approve or Reject: every change the run waits on, or Kai's turn), the same decision the
// Inbox makes; Continue goes on after a model's limit. A plan to steer opens it (it needs a choice).
// In the desktop app each new one is also a system notification, on any page: a click brings the
// app forward to it, and on macOS its buttons make the same decision without opening the app.
import { useEffect, useRef, useState } from "react";

import { continueLimited, decideChange, decideCoding } from "../core/agents";
import { desktopNotify } from "../core/desktop";
import { openDemoRequest } from "../core/demoRequest";
import { Ic } from "../core/icons";
import { go, useRoute } from "../core/nav";
import { waitingChanges } from "../core/presence";
import { CODING_AGENT, CODING_TOOLS } from "../data/seed-dotrix";
import { D, S, render, task } from "../data/store";
import { codingRunDecided, codingSessionDecided, isLive, live, runChangesDecided } from "../data/live";
import type { Notif } from "../data/types";
import { Face } from "../ui/face";
import { toast } from "../ui/toast";
import { useWorkspaceApprovals } from "../../lib/agent";
import { useCodingRun } from "../../lib/coding";
import { useLiveNotifications } from "../../lib/workspace-data";

interface Notice {
  key: string;
  at: number;
  c: string;
  name: string;
  title: string;
  text: string;
  mood: "needs" | "blocked";
  act?: { label: string; run: () => void };
  /** A real workspace's coding turn waiting for approval: decided here. */
  coding?: { workspaceId: string; projectId: string; runId: string };
  /** A real workspace's agent run paused on changes: decided here, all of them. */
  changes?: { workspaceId: string; projectId: string; runId: string };
  /** A real workspace's Kai session waiting on you (its waiting turn is found when you decide). */
  session?: { projectId: string; sessionId: string };
  /** The sample's approve and reject. */
  decide?: { approve: () => void; reject: () => void };
  open: () => void;
}

function notices(liveNotifs: Notif[] | undefined): Notice[] {
  const out: Notice[] = [];
  // One notice per reply: a single change can be approved here, several open the conversation.
  const byMsg = new Map<string, ReturnType<typeof waitingChanges>>();
  for (const w of waitingChanges()) byMsg.set(w.msg.id, [...(byMsg.get(w.msg.id) ?? []), w]);
  for (const ws of byMsg.values()) {
    const w = ws[0]!;
    const a = D().agents.find((x) => x.handle === w.agent);
    if (!a) continue;
    const steer = w.ch.kind === "checkpoint";
    const one = ws.length === 1 && !steer;
    out.push({
      key: w.msg.id,
      at: w.msg.at,
      c: a.c,
      name: a.name,
      title: steer ? "wants you to steer its plan" : "needs your approval",
      text: ws.length > 1 ? `${ws.length} changes · ${ws.map((x) => x.ch.title).join(", ")}` : w.ch.title,
      mood: "needs",
      decide: one ? { approve: () => decideChange(w.ch.id, true), reject: () => decideChange(w.ch.id, false) } : undefined,
      open: () => (isLive() ? go("chat", {}, { search: `thread=${w.th.id}` }) : openDemoRequest({ thread: w.th.id })),
    });
  }
  // A real workspace's approvals arrive as notifications.
  for (const n of liveNotifs ?? D().notifs) {
    if (n.read) continue;
    if (n.type === "approval" && n.codingRun && n.project && live.ws) {
      const runId = n.codingRun;
      out.push({
        key: n.id,
        at: n.at,
        c: CODING_AGENT.c,
        name: CODING_AGENT.name,
        title: "needs your approval",
        text: n.snippet || n.text,
        mood: "needs",
        coding: { workspaceId: live.ws.id, projectId: n.project, runId },
        open: () => go("inbox", {}, { search: `n=${n.id}` }),
      });
      continue;
    }
    if (n.type === "limit" && n.run && n.project) {
      const a = D().agents.find((x) => x.handle === n.by);
      if (!a) continue;
      const at = { thread: n.thread, project: n.project, run: n.run, notif: n.id };
      out.push({
        key: n.id,
        at: n.at,
        c: a.c,
        name: a.name,
        title: "stopped at its model's limit",
        text: n.snippet || n.text,
        mood: "blocked",
        act: { label: "Continue", run: () => continueLimited(at, false) },
        open: () => go("inbox", {}, { search: `n=${n.id}` }),
      });
      continue;
    }
    if ((n.type === "approval" || n.type === "checkpoint") && n.by) {
      const a = D().agents.find((x) => x.handle === n.by);
      // the seeded workspace's notifications repeat its conversations' changes, shown above
      if (!a || (n.thread && D().threads.some((t) => t.id === n.thread))) continue;
      out.push({
        key: n.id,
        at: n.at,
        c: a.c,
        name: a.name,
        title: n.type === "checkpoint" ? "wants you to steer its plan" : "needs your approval",
        text: n.snippet || n.text,
        mood: "needs",
        changes: n.type === "approval" && n.run && n.project && live.ws ? { workspaceId: live.ws.id, projectId: n.project, runId: n.run } : undefined,
        open: () => go("inbox", {}, { search: `n=${n.id}` }),
      });
    }
  }
  // A turn an approval notification already names is decided there, once.
  const notified = new Set((liveNotifs ?? []).filter((n) => n.type === "approval" && n.codingRun && !n.read).map((n) => `${n.project}:${n.task}`));
  for (const cs of D().coding) {
    const tool = CODING_TOOLS.find((t) => t.id === `agent:${cs.tool}`);
    const key = task(cs.task)?.key ?? "";
    const waits = cs.status === "awaiting_approval" || (isLive() && cs.status === "changes_ready");
    if (!tool || (!waits && cs.status !== "failed")) continue;
    if (waits && isLive() && notified.has(`${cs.project}:${cs.task}`)) continue;
    const open = () => (isLive() ? go("codes", {}, { search: `session=${cs.id}` }) : openDemoRequest({ task: cs.task }));
    out.push(
      cs.status === "failed"
        ? {
            key: `${cs.id}:failed`,
            at: cs.at,
            c: tool.c,
            name: tool.name,
            title: "couldn't finish",
            text: `${key} ${task(cs.task)?.title ?? ""}`,
            mood: "blocked",
            open,
          }
        : {
            key: cs.id,
            at: cs.at,
            c: tool.c,
            name: tool.name,
            title: cs.status === "changes_ready" ? "has changes to push" : "wants to start coding",
            text: `${key} ${task(cs.task)?.title ?? ""}`,
            mood: "needs",
            ...(isLive()
              ? { session: { projectId: cs.project, sessionId: cs.id } }
              : { decide: { approve: () => decideCoding(cs, true), reject: () => decideCoding(cs, false) } }),
            open,
          },
    );
  }
  // Decisions first (an agent waits on them), then what's blocked (a limit, a failed turn); newest first in each.
  const rank = (n: Notice) => (n.mood === "needs" ? 0 : 1);
  return out.filter((n) => !S.ui.noticesShut.includes(n.key)).sort((a, b) => rank(a) - rank(b) || b.at - a.at);
}

/** Floating bottom right; `inPanel` stacks them at the foot of the agents panel instead. */
export function Notices({ inPanel = false }: { inPanel?: boolean }) {
  const { route } = useRoute();
  const ref = useRef<HTMLDivElement>(null);
  const liveNotifs = useLiveNotifications(live.ws?.id, isLive());
  const all = notices(liveNotifs);
  useSystemNotices(all, !isLive() || liveNotifs !== undefined);
  const list = inPanel ? all : route === "home" ? all.slice(0, 1) : [];
  // Toasts sit above floating notices (both live bottom right).
  useEffect(() => {
    if (inPanel) {
      document.documentElement.style.setProperty("--notices-h", "0px");
      return;
    }
    const el = ref.current;
    const set = () => {
      const h = el?.offsetHeight ?? 0;
      document.documentElement.style.setProperty("--notices-h", `${h ? h + 8 : 0}px`);
    };
    set();
    if (!el) return;
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, [list.length, inPanel, route]);
  if (!list.length) return null;
  const shut = (key: string) => {
    S.ui.noticesShut = [...S.ui.noticesShut, key];
    render();
  };
  return (
    <div className={`notices ${inPanel ? "in-panel" : ""}`} ref={ref} role="region" aria-label="Waiting for you">
      {list.map((n) => (
        <div key={n.key} className={`notice ${n.mood}`}>
          <Face c={n.c} size={28} mood={n.mood} />
          <button className="notice-t" onClick={n.open}>
            <span>
              <b>{n.name}</b> {n.title}
            </span>
            <span className="notice-x">{n.text}</span>
          </button>
          {n.coding ? (
            <CodingNoticeActions {...n.coding} open={n.open} done={() => shut(n.key)} />
          ) : n.changes ? (
            <ChangeNoticeActions {...n.changes} open={n.open} done={() => shut(n.key)} />
          ) : n.session || n.decide ? (
            <Decide
              approve={async () => (n.session ? await codingSessionDecided(n.session.projectId, n.session.sessionId, true) : (n.decide!.approve(), true))}
              reject={async () => (n.session ? await codingSessionDecided(n.session.projectId, n.session.sessionId, false) : (n.decide!.reject(), true))}
              done={() => shut(n.key)}
            />
          ) : n.act ? (
            <ActionButton className="btn btn-sm btn-primary" onClick={n.act.run}>
              {n.act.label}
            </ActionButton>
          ) : (
            <ActionButton className="btn btn-sm btn-secondary" onClick={n.open}>
              Open
            </ActionButton>
          )}
          <ActionButton className="ibtn ibtn-xs" onClick={() => shut(n.key)} aria-label={`Close the notice from ${n.name}`}>
            <Ic n="x" s={13} />
          </ActionButton>
        </div>
      ))}
    </div>
  );
}

/** Reject and Approve buttons for a decision that resolves when it has gone through (or been refused). */
function Decide({ approve, reject, done }: { approve: () => Promise<boolean>; reject: () => Promise<boolean>; done: () => void }) {
  const [busy, setBusy] = useState(false);
  const run = (f: () => Promise<boolean>) => {
    setBusy(true);
    void f()
      .then((ok) => ok && done())
      .finally(() => setBusy(false));
  };
  return (
    <>
      <ActionButton className="btn btn-sm btn-secondary" disabled={busy} onClick={() => run(reject)}>
        Reject
      </ActionButton>
      <ActionButton className="btn btn-sm btn-primary" disabled={busy} onClick={() => run(approve)}>
        Approve
      </ActionButton>
    </>
  );
}

/** Approve or reject a turn of Kai's that waits on you, as Inbox does: to start, or its checked changes to be pushed. */
function CodingNoticeActions({
  workspaceId,
  projectId,
  runId,
  open,
  done,
}: {
  workspaceId: string;
  projectId: string;
  runId: string;
  open: () => void;
  done: () => void;
}) {
  const r = useCodingRun({ workspaceId, projectId }, runId).data;
  if (!r || !(r.status === "awaiting_approval" || r.status === "changes_ready") || !r.can_decide)
    return (
      <ActionButton className="btn btn-sm btn-secondary" onClick={open}>
        Open
      </ActionButton>
    );
  return <Decide approve={() => codingRunDecided(projectId, runId, true)} reject={() => codingRunDecided(projectId, runId, false)} done={done} />;
}

/** Approve or reject every change an agent's run waits on you for, as Inbox does. */
function ChangeNoticeActions({
  workspaceId,
  projectId,
  runId,
  open,
  done,
}: {
  workspaceId: string;
  projectId: string;
  runId: string;
  open: () => void;
  done: () => void;
}) {
  const approvals = useWorkspaceApprovals(workspaceId);
  const pending = (approvals.data ?? []).filter((a) => a.run_id === runId && a.status === "pending");
  if (!pending.length)
    return (
      <ActionButton className="btn btn-sm btn-secondary" onClick={open}>
        Open
      </ActionButton>
    );
  return <Decide approve={() => runChangesDecided(projectId, runId, true)} reject={() => runChangesDecided(projectId, runId, false)} done={done} />;
}

/** In the desktop app, each notice that appears while it runs becomes a system notification (what
 * already waited when it opened is on Home and in Inbox). Its click or button comes back here. */
function useSystemNotices(all: Notice[], loaded: boolean) {
  const latest = useRef(new Map<string, Notice>());
  latest.current = new Map(all.map((n) => [n.key, n]));
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    const bridge = desktopNotify();
    if (!bridge) return;
    return bridge.onAction((id, action) => {
      const n = latest.current.get(id);
      if (n) void systemAction(n, action);
    });
  }, []);
  const keys = all.map((n) => n.key).join(" ");
  useEffect(() => {
    const bridge = desktopNotify();
    if (!bridge || !loaded) return;
    if (seen.current === null) {
      seen.current = new Set(latest.current.keys());
      return;
    }
    for (const n of latest.current.values()) {
      if (seen.current.has(n.key)) continue;
      seen.current.add(n.key);
      const actions = n.act ? [n.act.label] : n.coding || n.changes || n.session || n.decide ? ["Approve", "Reject"] : [];
      void bridge.show({ id: n.key, title: `${n.name} ${n.title}`, body: n.text, actions }).catch(() => undefined);
    }
  }, [keys, loaded]);
}

/** A system notification's click opens the item; a button makes the notice's own decision, checked
 * against the API first: anything no longer simple to decide (decided elsewhere, a diff to read)
 * opens instead. */
async function systemAction(n: Notice, action: string | null) {
  if (action === null) return n.open();
  try {
    if (n.act && action === n.act.label) return n.act.run();
    const approve = action === "Approve";
    // The same decisions as the notice's buttons (they say how it went, and refetch what it changed).
    let ok: boolean;
    if (n.coding) ok = await codingRunDecided(n.coding.projectId, n.coding.runId, approve);
    else if (n.changes) ok = await runChangesDecided(n.changes.projectId, n.changes.runId, approve);
    else if (n.session) ok = await codingSessionDecided(n.session.projectId, n.session.sessionId, approve);
    else if (n.decide) ok = (approve ? n.decide.approve() : n.decide.reject(), true);
    else return n.open();
    if (!ok) return;
    S.ui.noticesShut = [...S.ui.noticesShut, n.key];
    render();
  } catch (e) {
    toast(e instanceof Error && e.message ? e.message : "That didn't go through; open it to try again", { kind: "err" });
  }
}
