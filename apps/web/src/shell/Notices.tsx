// Corner notices (after Orbit's): only what needs a person, with the action in the notice. An
// agent's change waiting for approval (Approve, or Open it), a plan to steer, a coding tool
// waiting to start or that couldn't finish. On Home only (elsewhere they'd cover the page), and
// only while the agents panel is closed (it lists the same things); the newest two, bottom
// right; closing one keeps it closed for this session. In a real workspace, the simple decisions
// are made in the notice itself, the same ones Inbox makes: a coding turn waiting to start, one
// small board change, and Continue for a run stopped at its model's limit. Anything to read first
// (a document's diff, several changes, Kai's checked changes, a plan) opens it instead.
// In the desktop app each new one is also a system notification, on any page: a click brings the
// app forward to it, and on macOS its buttons make the same decision without opening the app.
import { useEffect, useRef } from "react";

import { continueLimited, decideChange, decideCoding } from "../core/agents";
import { desktopNotify } from "../core/desktop";
import { openDemoRequest } from "../core/demoRequest";
import { Ic } from "../core/icons";
import { go, useRoute } from "../core/nav";
import { waitingChanges } from "../core/presence";
import { CODING_AGENT, CODING_TOOLS } from "../data/seed-dotrix";
import { D, S, render, task } from "../data/store";
import { isLive, live } from "../data/live";
import type { Notif } from "../data/types";
import { Face } from "../ui/face";
import { toast } from "../ui/toast";
import { useDecide, useWorkspaceApprovals } from "../../lib/agent";
import { api, unwrap } from "../../lib/api";
import { queryClient } from "../../lib/queryClient";
import { useCodingRun, useDecideCoding } from "../../lib/coding";
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
  /** A real workspace's agent run paused on changes: one small one is decided here. */
  changes?: { workspaceId: string; projectId: string; runId: string };
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
      act: one ? { label: "Approve", run: () => decideChange(w.ch.id, true) } : undefined,
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
  for (const cs of D().coding) {
    const tool = CODING_TOOLS.find((t) => t.id === `agent:${cs.tool}`);
    const key = task(cs.task)?.key ?? "";
    if (!tool || (cs.status !== "awaiting_approval" && cs.status !== "failed")) continue;
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
            title: "wants to start coding",
            text: `${key} ${task(cs.task)?.title ?? ""}`,
            mood: "needs",
            act: { label: "Approve", run: () => decideCoding(cs, true) },
            open,
          },
    );
  }
  return out.filter((n) => !S.ui.noticesShut.includes(n.key)).sort((a, b) => b.at - a.at);
}

/** Floating bottom right; `inPanel` stacks them at the foot of the agents panel instead. */
export function Notices({ inPanel = false }: { inPanel?: boolean }) {
  const { route } = useRoute();
  const ref = useRef<HTMLDivElement>(null);
  const narrow = typeof window !== "undefined" && window.matchMedia("(max-width: 900px)").matches;
  const liveNotifs = useLiveNotifications(live.ws?.id, isLive());
  const all = notices(liveNotifs);
  useSystemNotices(all, !isLive() || liveNotifs !== undefined);
  const list = route === "home" ? all.slice(0, narrow ? 1 : 2) : [];
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
          ) : n.act ? (
            <button className="btn btn-sm btn-primary" onClick={n.act.run}>
              {n.act.label}
            </button>
          ) : (
            <button className="btn btn-sm btn-secondary" onClick={n.open}>
              Open
            </button>
          )}
          <button className="ibtn ibtn-xs" onClick={() => shut(n.key)} aria-label={`Close the notice from ${n.name}`}>
            <Ic n="x" s={13} />
          </button>
        </div>
      ))}
    </div>
  );
}

/** Approve or reject a turn that waits to start, as Inbox does. Checked changes waiting to be pushed
 * open Inbox instead, where their files and any CI-sensitive ones are shown before accepting. */
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
  const scope = { workspaceId, projectId };
  const run = useCodingRun(scope, runId);
  const decide = useDecideCoding(scope, run.data?.issue_key ?? "");
  const r = run.data;
  if (!r || r.status !== "awaiting_approval" || !r.can_decide)
    return (
      <button className="btn btn-sm btn-secondary" onClick={open}>
        {r?.status === "changes_ready" ? "Review" : "Open"}
      </button>
    );
  const decision = (approve: boolean) => decide.mutate({ runId: r.id, decision: approve ? "approve" : "reject" }, { onSuccess: done });
  return (
    <>
      <button className="btn btn-sm btn-secondary" disabled={decide.isPending} onClick={() => decision(false)}>
        Reject
      </button>
      <button className="btn btn-sm btn-primary" disabled={decide.isPending} onClick={() => decision(true)}>
        Approve
      </button>
    </>
  );
}

// Board changes are short enough to decide from the notice; a document's edit has a diff to read.
const QUICK_TOOLS = new Set(["create_issue", "update_issue", "comment_issue", "link_items"]);

/** Approve or reject an agent's one waiting board change, as Inbox does; anything else opens Inbox. */
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
  const decide = useDecide({ workspaceId, projectId });
  const pending = (approvals.data ?? []).filter((a) => a.run_id === runId && a.status === "pending");
  const [only] = pending;
  if (pending.length !== 1 || !QUICK_TOOLS.has(only.tool))
    return (
      <button className="btn btn-sm btn-secondary" onClick={open}>
        {pending.length ? "Review" : "Open"}
      </button>
    );
  const decision = (approve: boolean) =>
    decide.mutate({ runId, decisions: [{ approval_id: only.id, decision: approve ? "approve" : "reject" }] }, { onSuccess: done });
  return (
    <>
      <button className="btn btn-sm btn-secondary" disabled={decide.isPending} onClick={() => decision(false)}>
        Reject
      </button>
      <button className="btn btn-sm btn-primary" disabled={decide.isPending} onClick={() => decision(true)}>
        Approve
      </button>
    </>
  );
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
      const actions = n.act ? [n.act.label] : n.coding || n.changes ? ["Approve", "Reject"] : [];
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
    if (n.coding) {
      const path = { workspace_id: n.coding.workspaceId, project_id: n.coding.projectId, coding_run_id: n.coding.runId };
      const run = await unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}", { params: { path } }));
      if (run.status !== "awaiting_approval" || !run.can_decide) return n.open();
      await unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/coding/runs/{coding_run_id}/decision", {
          params: { path },
          body: { decision: approve ? "approve" : "reject", reason: null },
        }),
      );
      toast(approve ? `Kai is starting on ${run.issue_key}` : `Rejected Kai's turn on ${run.issue_key}`);
    } else if (n.changes) {
      const { workspaceId, projectId, runId } = n.changes;
      const approvals = await unwrap(api.GET("/v1/workspaces/{workspace_id}/approvals", { params: { path: { workspace_id: workspaceId } } }));
      const pending = approvals.filter((a) => a.run_id === runId && a.status === "pending");
      if (pending.length !== 1 || !QUICK_TOOLS.has(pending[0].tool)) return n.open();
      await unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/decisions", {
          params: { path: { workspace_id: workspaceId, project_id: projectId, run_id: runId } },
          body: { decisions: [{ approval_id: pending[0].id, decision: approve ? "approve" : "reject" }] },
        }),
      );
      toast(approve ? "Approved" : "Rejected");
    } else return n.open();
    S.ui.noticesShut = [...S.ui.noticesShut, n.key];
    render();
  } catch (e) {
    toast(e instanceof Error && e.message ? e.message : "That didn't go through; open it to try again", { kind: "err" });
  } finally {
    void queryClient.invalidateQueries();
  }
}
