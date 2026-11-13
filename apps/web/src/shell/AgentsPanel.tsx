import { ActionButton } from "@dotrix/ui/components/action-button";
// The agents panel (after Orbit's): who needs you, who is working and on what, and who is free,
// each with a face and a "now" line; today's replies and tokens at the foot. It opens over the page
// from the launcher at the bottom right (a chat button, with the faces of whoever needs you or is
// working), on every page but Codes, never squeezing the page. A row opens where that agent's work
// is: its conversation, its coding session, or a new chat with it.
import { useEffect } from "react";

import { Ic } from "../core/icons";
import { openDemoRequest } from "../core/demoRequest";
import { go } from "../core/nav";
import { presence, today, type Presence } from "../core/presence";
import { D, S, me, render } from "../data/store";
import { Face } from "../ui/face";
import { useAgentActivity, useBuiltinTeam } from "@/lib/team";
import { isLive, live } from "../data/live";

/** The launcher opens and closes the panel. */
function toggleAgents() {
  S.ui.agentsSheet = !S.ui.agentsSheet;
  render();
}
/** Codes: the right side holds the session's own panels, so no agents panel or launcher there
 * (the bell and the corner notices still say what needs you). */
export const inCodeTab = () => /^\/w\/[^/]+\/codes\/?$/.test(location.pathname);
export const agentsShown = () => !inCodeTab() && S.ui.agentsSheet;

const LABEL: Record<Presence["state"], string> = { needs: "Needs you", working: "Working", blocked: "Blocked", idle: "Idle" };

function openWork(p: Presence) {
  S.ui.agentsSheet = false;
  if (!isLive() && (p.thread || p.session)) {
    openDemoRequest({ thread: p.thread, task: D().coding.find((c) => c.id === p.session)?.task });
    return;
  }
  if (p.thread) go("chat", {}, { search: `thread=${p.thread}${p.project ? `&project=${p.project}` : ""}` });
  else if (p.session) go("codes", {}, { search: `session=${p.session}${p.review ? "&panel=review" : ""}` });
  else go("chat", {}, { search: `new=1&agent=${p.id}` });
}

function Row({ p }: { p: Presence }) {
  return (
    <div
      className={`ap-row st-${p.state}`}
      role="button"
      tabIndex={0}
      onClick={() => openWork(p)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), openWork(p))}
    >
      <Face c={p.c} size={26} mood={p.mood} />
      <span className="ap-main">
        <span className="ap-top">
          <b>{p.name}</b>
          <span className="ap-role">{p.role}</span>
          <span className="sp" />
          <span className="ap-state">
            <i />
            {LABEL[p.state]}
          </span>
        </span>
        <span className="ap-now">{p.now}</span>
        {p.state === "working" && <span className="ap-bar" aria-hidden />}
        {p.approve && (
          <span className="ap-acts">
            {p.reject && (
              <ActionButton
                className="btn btn-sm btn-secondary"
                onClick={(e) => {
                  e.stopPropagation();
                  p.reject!();
                }}
              >
                Reject
              </ActionButton>
            )}
            <ActionButton
              className="btn btn-sm btn-primary"
              onClick={(e) => {
                e.stopPropagation();
                p.approve!();
              }}
            >
              Approve
            </ActionButton>
            <ActionButton className="btn btn-sm btn-ghost">Open</ActionButton>
          </span>
        )}
      </span>
    </div>
  );
}

function Group({ title, list }: { title: string; list: Presence[] }) {
  if (!list.length) return null;
  return (
    <section className="ap-group">
      <div className="ap-gh">
        {title}
        <span>{list.length}</span>
      </div>
      {list.map((p) => (
        <Row key={p.id} p={p} />
      ))}
    </section>
  );
}

/** Every agent's presence, named as the workspace's team names them. */
function useTeam(): Presence[] {
  const workspaceId = isLive() ? live.ws?.id : undefined;
  const activity = useAgentActivity(workspaceId);
  const roster = useBuiltinTeam(workspaceId);
  return presence(activity.data ?? []).map((item) => {
    const role = roster.data?.find(
      (agent) => agent.handle === (item.id === "auto" ? "project-manager" : item.id === "agent:coding-agent" ? "coding-agent" : item.id),
    );
    return role ? { ...item, name: role.name, role: role.role } : item;
  });
}

const ORDER: Record<Presence["state"], number> = { needs: 0, blocked: 1, working: 2, idle: 3 };

/** The button at the bottom right: up to three faces (whoever needs you first, then whoever is
 * working, else the team's first), and how many wait on you. Escape closes the panel. */
export function AgentsLauncher() {
  const all = useTeam();
  const open = agentsShown();
  const waiting = all.filter((p) => p.state === "needs" || p.state === "blocked").length;
  const faces = [...all].sort((a, b) => ORDER[a.state] - ORDER[b.state]).slice(0, 3);
  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && toggleAgents();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);
  return (
    <button
      className={`agents-launcher ${open ? "on" : ""}`}
      onClick={toggleAgents}
      aria-expanded={open}
      aria-controls="agents-panel"
      aria-label={open ? "Close the agents panel" : waiting ? `Agents: ${waiting} waiting on you` : "Agents"}
    >
      {open ? (
        <Ic n="x" s={18} />
      ) : (
        <span className="al-faces" aria-hidden>
          {faces.map((p) => (
            <span key={p.id}>
              <Face c={p.c} size={28} mood={p.mood} />
            </span>
          ))}
        </span>
      )}
      {!open && waiting > 0 && <span className="al-count num">{waiting}</span>}
    </button>
  );
}

export function AgentsPanel() {
  const all = useTeam();
  const by = (st: Presence["state"][]) => all.filter((p) => st.includes(p.state));
  const t = today();
  const admin = me()?.role === "Owner" || me()?.role === "Admin";
  return (
    <aside className="agents-panel sheet" id="agents-panel" aria-label="Agents">
      <div className="ap-h">
        <b>Agents</b>
        <span className="faint">
          {all.length - by(["idle"]).length} active · {by(["idle"]).length} free
        </span>
        <span className="sp" />
        <ActionButton className="ibtn ibtn-sm" onClick={toggleAgents} aria-label="Hide the agents panel" data-tip="Hide">
          <Ic n="chevron-down" s={15} />
        </ActionButton>
      </div>
      <div className="ap-body">
        <p className="ap-team-note">7 built-in agents · Nova leads the team</p>
        <Group title="Needs you" list={by(["needs", "blocked"])} />
        <Group title="Working" list={by(["working"])} />
        <Group title="Free" list={by(["idle"])} />
      </div>
      <div className="ap-foot">
        <div>
          <span>Replies today</span>
          <b className="num">{t.replies}</b>
        </div>
        {admin && (
          <div>
            <span>Tokens today</span>
            <b className="num">{t.tokens >= 1000 ? `${(t.tokens / 1000).toFixed(1)}k` : t.tokens}</b>
          </div>
        )}
        <div>
          <span>Waiting on you</span>
          <b className="num">{by(["needs", "blocked"]).length}</b>
        </div>
      </div>
    </aside>
  );
}
