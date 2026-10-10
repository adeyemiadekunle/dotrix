// The agents panel (after Orbit's): on the right of every page, who needs you, who is working
// and on what, and who is free, each with a face and a "now" line; today's replies and tokens
// at the foot. Open by default on wide screens (Settings keep it per browser), a sheet on
// narrower ones. A row opens where that agent's work is: its conversation, its coding
// session, or a new chat with it.
import { Ic } from "../core/icons";
import { go } from "../core/nav";
import { presence, today, type Presence } from "../core/presence";
import { S, me, render, save } from "../data/store";
import { Face } from "../ui/face";

const WIDE = "(min-width: 1200px)";
export const panelWide = () => typeof window !== "undefined" && window.matchMedia(WIDE).matches;

/** The top bar's button: the panel on wide screens (remembered), the sheet otherwise. */
export function toggleAgents() {
  if (panelWide()) {
    S.prefs.agentsPanel = !S.prefs.agentsPanel;
    save();
  } else S.ui.agentsSheet = !S.ui.agentsSheet;
  render();
}
/** Chat's Code tab: the right side holds the session's own panels, so no agents panel there
 * (the bell and the corner notices still say what needs you). */
export const inCodeTab = () => /\/chat\/?$/.test(location.pathname) && new URLSearchParams(location.search).get("tab") === "coding";
export const agentsShown = () => !inCodeTab() && (panelWide() ? S.prefs.agentsPanel : S.ui.agentsSheet);

const LABEL: Record<Presence["state"], string> = { needs: "Needs you", working: "Working", blocked: "Blocked", idle: "Idle" };

function openWork(p: Presence) {
  S.ui.agentsSheet = false;
  if (p.thread) go("chat", {}, { search: `thread=${p.thread}` });
  else if (p.session) go("chat", {}, { search: `tab=coding&session=${p.session}` });
  else go("chat", {}, { search: `new=1&agent=${p.id}` });
}

function Row({ p }: { p: Presence }) {
  return (
    <div className={`ap-row st-${p.state}`} role="button" tabIndex={0} onClick={() => openWork(p)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), openWork(p))}>
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
            <button
              className="btn btn-sm btn-primary"
              onClick={(e) => {
                e.stopPropagation();
                p.approve!();
              }}
            >
              Approve
            </button>
            <button className="btn btn-sm btn-ghost">Open</button>
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

export function AgentsPanel() {
  const all = presence();
  const by = (st: Presence["state"][]) => all.filter((p) => st.includes(p.state));
  const t = today();
  const admin = me()?.role === "Owner" || me()?.role === "Admin";
  return (
    <aside className="agents-panel" aria-label="Agents">
      <div className="ap-h">
        <b>Agents</b>
        <span className="faint">
          {all.length - by(["idle"]).length} active · {by(["idle"]).length} free
        </span>
        <span className="sp" />
        <button className="ibtn ibtn-sm" onClick={toggleAgents} aria-label="Hide the agents panel" data-tip="Hide">
          <Ic n="panel-right-close" s={15} />
        </button>
      </div>
      <div className="ap-body">
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
