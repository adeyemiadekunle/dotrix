// Corner notices (after Orbit's): only what needs a person, with the action in the notice. An
// agent's change waiting for approval (Approve, or Open it), a plan to steer, a coding tool
// waiting to start or that couldn't finish. On Home only (elsewhere they'd cover the page), and
// only while the agents panel is closed (it lists the same things); the newest two, bottom
// right; closing one keeps it closed for this session.
import { useEffect, useRef } from "react";

import { decideChange, decideCoding } from "../core/agents";
import { Ic } from "../core/icons";
import { go, useRoute } from "../core/nav";
import { waitingChanges } from "../core/presence";
import { CODING_TOOLS } from "../data/seed-dotrix";
import { D, S, render, task } from "../data/store";
import { Face } from "../ui/face";

interface Notice {
  key: string;
  at: number;
  c: string;
  name: string;
  title: string;
  text: string;
  mood: "needs" | "blocked";
  act?: { label: string; run: () => void };
  open: () => void;
}

function notices(): Notice[] {
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
      open: () => go("chat", {}, { search: `thread=${w.th.id}` }),
    });
  }
  // A real workspace's approvals arrive as notifications.
  for (const n of D().notifs)
    if ((n.type === "approval" || n.type === "checkpoint") && !n.read && n.by) {
      const a = D().agents.find((x) => x.handle === n.by);
      // the seeded workspace's notifications repeat its conversations' changes, shown above
      if (!a || (n.thread && D().threads.some((t) => t.id === n.thread))) continue;
      out.push({ key: n.id, at: n.at, c: a.c, name: a.name, title: n.type === "checkpoint" ? "wants you to steer its plan" : "needs your approval", text: n.snippet || n.text, mood: "needs", open: () => go("notifications", {}, { search: `n=${n.id}` }) });
    }
  for (const cs of D().coding) {
    const tool = CODING_TOOLS.find((t) => t.id === `agent:${cs.tool}`);
    const key = task(cs.task)?.key ?? "";
    if (!tool || (cs.status !== "awaiting_approval" && cs.status !== "failed")) continue;
    const open = () => go("chat", {}, { search: `tab=coding&session=${cs.id}` });
    out.push(
      cs.status === "failed"
        ? { key: `${cs.id}:failed`, at: cs.at, c: tool.c, name: tool.name, title: "couldn't finish", text: `${key} ${task(cs.task)?.title ?? ""}`, mood: "blocked", open }
        : { key: cs.id, at: cs.at, c: tool.c, name: tool.name, title: "wants to start coding", text: `${key} ${task(cs.task)?.title ?? ""}`, mood: "needs", act: { label: "Approve", run: () => decideCoding(cs, true) }, open },
    );
  }
  return out.filter((n) => !S.ui.noticesShut.includes(n.key)).sort((a, b) => b.at - a.at);
}

/** Floating bottom right; `inPanel` stacks them at the foot of the agents panel instead. */
export function Notices({ inPanel = false }: { inPanel?: boolean }) {
  const { route } = useRoute();
  const ref = useRef<HTMLDivElement>(null);
  const narrow = typeof window !== "undefined" && window.matchMedia("(max-width: 900px)").matches;
  const list = route === "home" ? notices().slice(0, narrow ? 1 : 2) : [];
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
          {n.act ? (
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
