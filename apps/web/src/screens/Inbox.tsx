// Gr8r's Inbox (gr8r-studio/src/pages/inbox.js) for what people send you (mentions, assignments,
// comments), and Notifications (pages/notifications.js) for what the agents need: changes to
// approve, plans to steer, findings, decisions; with the change itself in the detail.
import type { CSSProperties } from "react";

import { decideCoding } from "../core/agents";
import { openTask } from "../core/actions";
import { Ic } from "../core/icons";
import { go, useRoute } from "../core/nav";
import { ago, dayBucket } from "../core/utils";
import { D, S, commentsOf, mutate, pColor, proj, render, task, who } from "../data/store";
import type { Notif } from "../data/types";
import { ChangeCard } from "../components/Changes";
import { notifsRead } from "../data/live";
import { CellAssignee, CellDue, CellPrio, CellStatus } from "../components/TaskList";
import { CommentBox, CommentItem } from "../overlays/Drawer";
import { AGENT_ITEMS, PEOPLE_ITEMS } from "../shell/Shell";
import { Av, CommentText, Empty } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;

const projOf = (n: Notif) => (n.project ? proj(n.project) : n.task ? proj(task(n.task)?.project) : null);

export function NotifText({ n }: { n: Notif }) {
  const t = n.task ? task(n.task) : null;
  const p = projOf(n);
  if (!n.by && p && !t) return <b style={{ fontWeight: 600 }}>{n.text}</b>;
  if (!n.by && t)
    return (
      <>
        <b style={{ fontWeight: 600 }}>{t.title}</b> <span className="muted">{n.text}</span>
      </>
    );
  return (
    <>
      <b style={{ fontWeight: 600 }}>{who(n.by)?.name}</b> <span className="muted">{n.text}</span> {t && <b style={{ fontWeight: 500 }}>{t.title}</b>}
    </>
  );
}
export function NotifIcon({ n }: { n: Notif }) {
  if (n.by) return <Av id={n.by} cls="md" tip={false} />;
  const i = n.type === "update" && n.project ? "triangle-alert" : "clock";
  return (
    <span className="av md" style={css({ "--c": n.project ? "var(--red)" : "var(--amber)" })}>
      <Ic n={i} s={13} />
    </span>
  );
}
const TYPE_IC: Record<string, string> = {
  mention: "at-sign",
  assign: "user-plus",
  comment: "message-square",
  update: "refresh-cw",
  approval: "shield-check",
  checkpoint: "map",
  finding: "search-check",
  decided: "check-check",
};

function toggleRead(id: string) {
  const n = D().notifs.find((x) => x.id === id)!;
  mutate(() => (n.read = !n.read));
  if (n.read) notifsRead([n.id]); // the API keeps read, not unread
}
function markAllRead(types: string[]) {
  const ns = D().notifs.filter((n) => types.includes(n.type) && !n.read);
  mutate(() => ns.forEach((n) => (n.read = true)));
  notifsRead(ns.map((n) => n.id));
}
function markRead(n: Notif) {
  mutate(() => (n.read = true));
  notifsRead([n.id]);
}

function Item({ n, on, select }: { n: Notif; on: boolean; select: (id: string) => void }) {
  const p = projOf(n);
  return (
    <div
      className="row"
      style={{ alignItems: "flex-start", gap: 10, padding: "12px var(--gutter)", borderBottom: "1px solid var(--divider)", cursor: "pointer", position: "relative", background: on ? "var(--surface-2)" : undefined }}
      onClick={() => select(n.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && select(n.id)}
    >
      {!n.read && <span style={{ position: "absolute", left: 6, top: 22, width: 6, height: 6, borderRadius: "50%", background: "var(--acc)" }} aria-label="Unread" />}
      <NotifIcon n={n} />
      <div className="grow" style={{ fontSize: 13, lineHeight: 1.45, minWidth: 0 }}>
        <div>
          <NotifText n={n} />
        </div>
        <div className="trunc muted" style={{ fontSize: 12.5, marginTop: 2 }}>
          <CommentText text={n.snippet} />
        </div>
        <div className="row" style={{ gap: 6, marginTop: 5, fontSize: 11.5, color: "var(--text-3)" }}>
          <Ic n={TYPE_IC[n.type] ?? "bell"} s={11} />
          {p && (
            <>
              <span className="pdot" style={css({ "--c": pColor(p), width: 6, height: 6 })} />
              {p.name}
            </>
          )}
          <span>·</span>
          <span>{ago(n.at)}</span>
        </div>
      </div>
      <button
        className="ibtn ibtn-xs"
        onClick={(e) => {
          e.stopPropagation();
          toggleRead(n.id);
        }}
        data-tip={n.read ? "Mark as unread" : "Mark as read"}
        aria-label={n.read ? "Mark as unread" : "Mark as read"}
      >
        <Ic n={n.read ? "mail" : "mail-open"} s={13} />
      </button>
    </div>
  );
}

function SelectPrompt({ icon, title, text }: { icon: string; title: string; text: string }) {
  return (
    <div className="fullstate">
      <div className="box">
        <div className="empty-state" style={{ padding: 0 }}>
          <div className="glyph">
            <Ic n={icon} s={20} />
          </div>
          <h2 className="es-h">{title}</h2>
          <p>{text}</p>
        </div>
      </div>
    </div>
  );
}

function TaskPreview({ n, onBack }: { n: Notif; onBack: () => void }) {
  const t = n.task ? task(n.task) : null;
  const p = projOf(n);
  if (!t)
    return (
      <div style={{ padding: "24px 28px" }}>
        <button className="btn btn-sm btn-ghost" onClick={onBack} style={{ margin: "-4px 0 12px -8px" }}>
          <Ic n="arrow-left" s={14} />
          Back
        </button>
        <div className="alert danger">
          <Ic n="triangle-alert" s={16} />
          <div>
            <b>{n.text}</b>
            <div className="muted" style={{ marginTop: 2 }}>
              {n.snippet}
            </div>
          </div>
        </div>
        {p && (
          <div style={{ marginTop: 14 }}>
            <button className="btn btn-secondary" onClick={() => go("project", { id: p.key, tab: "overview" })}>
              Open project
            </button>
          </div>
        )}
      </div>
    );
  const cs = commentsOf(t.id).slice(-4);
  return (
    <>
      <div className="row" style={{ height: 46, padding: "0 16px", borderBottom: "1px solid var(--border)", gap: 8, flexShrink: 0 }}>
        <button className="ibtn ibtn-sm" onClick={onBack} aria-label="Back">
          <Ic n="arrow-left" s={15} />
        </button>
        <span className="pdot" style={css({ "--c": pColor(p!) })} />
        <span className="muted" style={{ fontSize: 12.5 }}>
          {p?.name}
        </span>
        <span className="faint mono">{t.key}</span>
        <span className="sp" />
        <button className="btn btn-sm btn-secondary" onClick={() => openTask(t.id)}>
          <Ic n="panel-right-open" s={14} />
          Open task
        </button>
      </div>
      <div style={{ padding: "24px 28px", maxWidth: 720, width: "100%" }}>
        <h2 style={{ fontSize: "var(--fs-xl)", margin: "0 0 10px", fontWeight: 600, letterSpacing: "-.015em" }}>{t.title}</h2>
        <div className="row" style={{ flexWrap: "wrap", gap: 4, marginBottom: 18 }}>
          <CellStatus t={t} />
          <CellAssignee t={t} />
          <CellPrio t={t} />
          <CellDue t={t} />
        </div>
        <div className="eyebrow" style={{ marginBottom: 4 }}>
          Conversation
        </div>
        {cs.length ? cs.map((c) => <CommentItem key={c.id} c={c} />) : <p className="muted">{n.snippet}</p>}
        <div style={{ marginTop: 10 }}>
          <CommentBox t={t} id="inbox-reply" placeholder="Reply… use @ to mention" label="Reply" />
        </div>
      </div>
    </>
  );
}

export function Inbox() {
  const cats = [
    ["all", "All"],
    ["mention", "Mentions"],
    ["assign", "Assignments"],
    ["comment", "Comments"],
  ];
  const cat = S.ui.inboxCat;
  let ns = D()
    .notifs.filter((n) => PEOPLE_ITEMS.includes(n.type))
    .sort((a, b) => b.at - a.at);
  const count = (k: string) => ns.filter((n) => (k === "all" || n.type === k) && !n.read).length;
  ns = ns.filter((n) => cat === "all" || n.type === cat);
  if (S.ui.inboxUnread) ns = ns.filter((n) => !n.read);
  const sel = D().notifs.find((n) => n.id === S.ui.inboxSel) || null;
  const select = (id: string) => {
    S.ui.inboxSel = id;
    const n = D().notifs.find((x) => x.id === id);
    if (n && !n.read) markRead(n);
    else render();
  };
  return (
    <div className="page flush">
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,420px) minmax(0,1fr)", flex: 1, minHeight: 0 }} className="inbox-grid">
        <style>{`@media(max-width:900px){.inbox-grid{grid-template-columns:minmax(0,1fr)!important}.inbox-prev{display:${sel ? "flex" : "none"}!important;position:fixed;inset:0;z-index:48;background:var(--surface)}}`}</style>
        <div style={{ borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ padding: "18px var(--gutter) 0" }} className="row">
            <h1 style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600, letterSpacing: "-.015em" }}>Inbox</h1>
            <span className="sp" />
            <label className="row" style={{ fontSize: 12, color: "var(--text-2)", gap: 6, cursor: "pointer" }}>
              <input type="checkbox" className="toggle" checked={S.ui.inboxUnread} onChange={() => ((S.ui.inboxUnread = !S.ui.inboxUnread), render())} />
              Unread
            </label>
            <button className="ibtn ibtn-sm" onClick={() => markAllRead(PEOPLE_ITEMS)} data-tip="Mark all as read" aria-label="Mark all as read">
              <Ic n="check-check" s={15} />
            </button>
          </div>
          <div className="tabs inbox-tabs" role="tablist">
            {cats.map(([k, n]) => (
              <button key={k} role="tab" className={`tab ${cat === k ? "on" : ""}`} onClick={() => ((S.ui.inboxCat = k!), render())}>
                {n}
                {count(k!) > 0 && <span className="cnt">{count(k!)}</span>}
              </button>
            ))}
          </div>
          <div className="inbox-list">
            {ns.length ? (
              ns.map((n) => <Item key={n.id} n={n} on={sel?.id === n.id} select={select} />)
            ) : (
              <Empty icon="inbox" title="You're all caught up." text={S.ui.inboxUnread ? "No unread notifications in this category." : "New mentions, assignments, and comments will show up here."} cls="sm" />
            )}
          </div>
        </div>
        <div className="inbox-prev" style={{ display: "flex", flexDirection: "column", minHeight: 0, overflowY: "auto" }}>
          {sel ? <TaskPreview n={sel} onBack={() => ((S.ui.inboxSel = null), render())} /> : <SelectPrompt icon="mail-open" title="Select a notification" text="Read the conversation and reply without leaving your inbox." />}
        </div>
      </div>
    </div>
  );
}

/* ---------- Notifications: what the agents need from you ---------- */

function AgentDetail({ n, onBack }: { n: Notif; onBack: () => void }) {
  const th = n.thread ? D().threads.find((t) => t.id === n.thread) : null;
  const cs = n.task ? D().coding.find((c) => c.task === n.task && (c.status === "awaiting_approval" || n.type !== "approval")) : null;
  const t = n.task ? task(n.task) : null;
  const p = projOf(n);
  const changes = th?.messages.flatMap((m) => m.changes ?? []) ?? [];
  return (
    <>
      <div className="row" style={{ height: 46, padding: "0 16px", borderBottom: "1px solid var(--border)", gap: 8, flexShrink: 0 }}>
        <button className="ibtn ibtn-sm" onClick={onBack} aria-label="Back">
          <Ic n="arrow-left" s={15} />
        </button>
        {p && (
          <>
            <span className="pdot" style={css({ "--c": pColor(p) })} />
            <span className="muted" style={{ fontSize: 12.5 }}>
              {p.name}
            </span>
          </>
        )}
        <span className="sp" />
        {th && (
          <button className="btn btn-sm btn-secondary" onClick={() => go("chat", {}, { search: `thread=${th.id}` })}>
            <Ic n="message-square" s={14} />
            Open the conversation
          </button>
        )}
        {cs && (
          <button className="btn btn-sm btn-secondary" onClick={() => go("chat", {}, { search: `tab=coding&session=${cs.id}` })}>
            <Ic n="code" s={14} />
            Open the session
          </button>
        )}
        {t && (
          <button className="btn btn-sm btn-ghost" onClick={() => openTask(t.id)}>
            <Ic n="panel-right-open" s={14} />
            Open task
          </button>
        )}
      </div>
      <div style={{ padding: "24px 28px", maxWidth: 760, width: "100%" }}>
        <div className="row" style={{ gap: 10, marginBottom: 6 }}>
          <NotifIcon n={n} />
          <div style={{ fontSize: 14 }}>
            <NotifText n={n} />
          </div>
        </div>
        <div className="faint" style={{ fontSize: 12, marginBottom: 16 }}>
          {ago(n.at)}
          {th && ` · in “${th.title}”`}
        </div>
        {th && (
          <>
            <div className="eyebrow" style={{ marginBottom: 2 }}>
              {n.type === "checkpoint" ? "The plan" : "Changes"}
            </div>
            {changes.length ? changes.map((c) => <ChangeCard key={c.id} ch={c} />) : <p className="muted">{n.snippet}</p>}
          </>
        )}
        {cs && t && (
          <div className="change">
            <div className="change-h">
              <Ic n="code" s={14} />
              <span className="muted">Code</span>
              <b style={{ fontWeight: 500 }}>
                {t.key} {t.title}
              </b>
            </div>
            <div className="change-b">
              <div className="muted" style={{ marginBottom: 4 }}>
                {who(cs.by)?.name} asked {cs.tool === "codex" ? "Codex" : "Claude Code"}:
              </div>
              {cs.turns.at(-1)?.ask}
            </div>
            {cs.status === "awaiting_approval" ? (
              <div className="change-f">
                <span className="faint" style={{ fontSize: 12 }}>
                  It works on a branch and opens a pull request; a person merges.
                </span>
                <span className="sp" />
                <button className="btn btn-sm btn-secondary" onClick={() => decideCoding(cs, false)}>
                  Reject
                </button>
                <button className="btn btn-sm btn-primary" onClick={() => decideCoding(cs, true)}>
                  <Ic n="check" s={13} />
                  Approve
                </button>
              </div>
            ) : (
              <div className="change-f">
                <span className="badge">{cs.status.replace(/_/g, " ")}</span>
              </div>
            )}
          </div>
        )}
        {!th && !cs && (
          <div className="alert info">
            <Ic n={TYPE_IC[n.type] ?? "bell"} s={16} />
            <div>
              <CommentText text={n.snippet} />
              {t && (
                <div style={{ marginTop: 8 }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => openTask(t.id)}>
                    Open {t.key}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

export function Notifications() {
  const { search } = useRoute();
  const tabs = [
    ["all", "All"],
    ["approval", "Approvals"],
    ["checkpoint", "Plans"],
    ["finding", "Findings"],
    ["decided", "Decided"],
    ["update", "Updates"],
  ];
  const tab = search.get("tab") || S.ui.notifTab;
  const f = S.ui.notifFilter;
  const mine = D()
    .notifs.filter((n) => AGENT_ITEMS.includes(n.type))
    .sort((a, b) => b.at - a.at);
  const unread = mine.filter((n) => !n.read).length;
  const count = (k: string) => mine.filter((n) => (k === "all" || n.type === k) && !n.read).length;
  let ns = mine.filter((n) => tab === "all" || n.type === tab);
  if (f === "unread") ns = ns.filter((n) => !n.read);
  const selId = search.get("n") || S.ui.notifSel;
  const sel = D().notifs.find((n) => n.id === selId) || null;
  const select = (id: string) => {
    S.ui.notifSel = id;
    const n = D().notifs.find((x) => x.id === id);
    // Approvals and plans stay unread until decided; the rest are read once opened.
    if (n && !n.read && n.type !== "approval" && n.type !== "checkpoint") markRead(n);
    go("notifications", {}, { replace: true, search: `n=${id}${tab !== "all" ? `&tab=${tab}` : ""}` });
  };
  const buckets: Record<string, Notif[]> = {};
  ns.forEach((n) => (buckets[dayBucket(n.at)] ||= []).push(n));
  return (
    <div className="page flush">
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,440px) minmax(0,1fr)", flex: 1, minHeight: 0 }} className="inbox-grid">
        <style>{`@media(max-width:900px){.inbox-grid{grid-template-columns:minmax(0,1fr)!important}.inbox-prev{display:${sel ? "flex" : "none"}!important;position:fixed;inset:0;z-index:48;background:var(--surface)}}`}</style>
        <div style={{ borderRight: "1px solid var(--border)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ padding: "18px var(--gutter) 0" }} className="row">
            <h1 className="row" style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600, letterSpacing: "-.015em", gap: 10 }}>
              Notifications {unread > 0 && <span className="badge accent">{unread}</span>}
            </h1>
            <span className="sp" />
            <div className="seg">
              {(
                [
                  ["all", "All"],
                  ["unread", "Unread"],
                ] as const
              ).map(([k, n]) => (
                <button key={k} className={f === k ? "on" : ""} onClick={() => ((S.ui.notifFilter = k), render())}>
                  {n}
                </button>
              ))}
            </div>
            <button className="ibtn ibtn-sm" onClick={() => markAllRead(["finding", "decided", "update"])} data-tip="Mark all as read (approvals stay until decided)" aria-label="Mark all as read">
              <Ic n="check-check" s={15} />
            </button>
            <button className="ibtn ibtn-sm" onClick={() => go("settings", { sec: "notif-email" })} data-tip="Notification preferences" aria-label="Notification preferences">
              <Ic n="settings-2" s={15} />
            </button>
          </div>
          <div className="tabs inbox-tabs" role="tablist">
            {tabs.map(([k, n]) => (
              <button key={k} role="tab" className={`tab ${tab === k ? "on" : ""}`} onClick={() => ((S.ui.notifTab = k!), go("notifications", {}, { replace: true, search: k === "all" ? "" : `tab=${k}` }))}>
                {n}
                {count(k!) > 0 && <span className="cnt">{count(k!)}</span>}
              </button>
            ))}
          </div>
          <div className="inbox-list">
            {ns.length ? (
              Object.entries(buckets).map(([b, list]) => (
                <div key={b}>
                  <div className="day-h" style={{ padding: "0 var(--gutter)" }}>
                    {b}
                  </div>
                  {list.map((n) => (
                    <Item key={n.id} n={n} on={sel?.id === n.id} select={select} />
                  ))}
                </div>
              ))
            ) : (
              <Empty icon="bell-off" title="You're all caught up." text="Nothing waits for you. When an agent wants to change something, it shows up here." cls="sm">
                {f === "unread" && (
                  <button className="btn btn-secondary btn-sm" onClick={() => ((S.ui.notifFilter = "all"), render())}>
                    Show all
                  </button>
                )}
              </Empty>
            )}
          </div>
        </div>
        <div className="inbox-prev" style={{ display: "flex", flexDirection: "column", minHeight: 0, overflowY: "auto" }}>
          {sel ? (
            <AgentDetail n={sel} onBack={() => ((S.ui.notifSel = null), go("notifications", {}, { replace: true, search: tab !== "all" ? `tab=${tab}` : "" }))} />
          ) : (
            <SelectPrompt icon="shield-check" title="Select a notification" text="Approve or reject an agent's changes, steer its plan, or follow up on a finding." />
          )}
        </div>
      </div>
    </div>
  );
}
