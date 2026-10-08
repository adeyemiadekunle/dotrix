// Gr8r's settings (gr8r-studio/src/pages/settings.js): a left nav of sections, each a set of rows.
// dotrix adds the agents' sections (owners and admins): Agents, Rules and skills, Automations,
// GitHub, What members can do, Audit log; and Devices and tokens (the CLI) under Security.
import { useState, type CSSProperties, type ReactNode } from "react";

import { copy, openPop, setPref } from "../core/actions";
import { Ic, WsLogo } from "../core/icons";
import { invite, newTeam } from "../core/more";
import { go, useRoute } from "../core/nav";
import { ago, dOff, fmtDate, uid } from "../core/utils";
import { D, S, me, mutate, proj, render, save, visibleProjects, who } from "../data/store";
import { SHORTCUTS } from "../overlays/Modals";
import { Av, Empty, PIcon } from "../ui/helpers";
import { toast } from "../ui/toast";
import { restoreProject } from "./Archive";
import { PermsTable, TeamsGrid } from "./Members";

const css = (o: Record<string, string | number>) => o as CSSProperties;

export const SET_NAV: [string, [string, string, string][], boolean?][] = [
  [
    "General",
    [
      ["workspace", "Workspace", "building-2"],
      ["appearance", "Appearance", "palette"],
      ["language", "Language", "languages"],
      ["datetime", "Date & time", "clock"],
    ],
  ],
  [
    "Workspace",
    [
      ["members", "Members", "users"],
      ["teams", "Teams", "users-round"],
      ["projects", "Projects", "folder-kanban"],
      ["permissions", "Permissions", "shield"],
    ],
  ],
  [
    "Agents",
    [
      ["agents", "Agents", "bot"],
      ["rules", "Rules and skills", "scroll-text"],
      ["automations", "Automations", "zap"],
      ["github", "GitHub", "github"],
      ["audit", "Audit log", "list-checks"],
    ],
    true,
  ],
  [
    "Notifications",
    [
      ["notif-email", "Email", "mail"],
      ["notif-push", "Push", "smartphone"],
      ["notif-mentions", "Mentions", "at-sign"],
      ["notif-assign", "Task assignments", "user-check"],
      ["notif-agents", "Agents", "sparkles"],
    ],
  ],
  [
    "Personal",
    [
      ["profile", "Profile", "user"],
      ["preferences", "Preferences", "sliders-horizontal"],
      ["shortcuts", "Keyboard shortcuts", "keyboard"],
    ],
  ],
  [
    "Security",
    [
      ["password", "Password", "key-round"],
      ["sessions", "Sessions", "monitor-smartphone"],
      ["devices", "Devices and tokens", "terminal"],
      ["2fa", "Two-factor authentication", "shield-check"],
    ],
  ],
  [
    "Billing",
    [
      ["plan", "Plan", "gem"],
      ["payment", "Payment", "credit-card"],
      ["invoices", "Invoices", "receipt"],
    ],
  ],
];

/* ---------- rows and controls ---------- */
type Loose = Record<string, unknown>;
const P = () => S.prefs as unknown as Loose;
const setP = (k: string, v: unknown) => {
  P()[k] = v;
  save();
  render();
};
const NP = () => D().notifPrefs;
const setNP = (k: string, v: boolean) => mutate(() => (D().notifPrefs[k] = v));

function SRow({ t, d, children }: { t: ReactNode; d?: ReactNode; children?: ReactNode }) {
  return (
    <div className="srow">
      <div>
        <div className="t">{t}</div>
        {d && <div className="d">{d}</div>}
      </div>
      <div className="row">{children}</div>
    </div>
  );
}
function Tog({ on, set, label }: { on: boolean; set: (v: boolean) => void; label: string }) {
  return <input type="checkbox" className="toggle" checked={on} onChange={(e) => set(e.target.checked)} aria-label={label} />;
}
const PTog = ({ k, def = true }: { k: string; def?: boolean }) => <Tog on={P()[k] === undefined ? def : Boolean(P()[k])} set={(v) => setP(k, v)} label={k} />;
const NTog = ({ k, def = false }: { k: string; def?: boolean }) => <Tog on={NP()[k] === undefined ? def : Boolean(NP()[k])} set={(v) => setNP(k, v)} label={k} />;
function Sel({ k, opts, v }: { k: string; opts: (string | [string, string])[]; v: unknown }) {
  return (
    <select className="select" style={{ width: "auto", minWidth: 180 }} value={String(v)} onChange={(e) => setP(k, k === "weekStart" ? +e.target.value : e.target.value)} aria-label={k}>
      {opts.map((o) => {
        const [val, n] = Array.isArray(o) ? o : [o, o];
        return (
          <option key={val} value={val}>
            {n}
          </option>
        );
      })}
    </select>
  );
}
function Seg({ k, opts }: { k: "side" | "density"; opts: string[] }) {
  return (
    <div className="seg">
      {opts.map((o) => (
        <button key={o} className={S.prefs[k] === o ? "on" : ""} onClick={() => setPref(k, o)}>
          {o[0]!.toUpperCase() + o.slice(1)}
        </button>
      ))}
    </div>
  );
}

const ACCENTS: [string, string][] = [
  ["indigo", "#4B5BD6"],
  ["blue", "#2F6CD4"],
  ["violet", "#7348CC"],
  ["teal", "#1A7F7A"],
  ["rose", "#B93D68"],
  ["graphite", "#34332F"],
];

function ThemeCards() {
  const L = { bg: "#FBFAF8", s: "#F2F1EE", t: "#1D1C1A", b: "#E3E1DC", a: "#4B5BD6" };
  const Dk = { bg: "#1D1D1C", s: "#151514", t: "#ECEAE5", b: "#333230", a: "#8E9AF3" };
  const pv = (c: typeof L) => (
    <>
      <div className="s" style={{ background: c.s }}>
        <i style={{ background: c.b, width: "70%" }} />
        <i style={{ background: c.a, width: "55%" }} />
        <i style={{ background: c.b, width: "80%" }} />
        <i style={{ background: c.b, width: "60%" }} />
      </div>
      <div className="m" style={{ background: c.bg }}>
        <i style={{ background: c.t, width: "45%", height: 7 }} />
        <i style={{ background: c.b }} />
        <i style={{ background: c.b, width: "80%" }} />
        <i style={{ background: c.a, width: "30%", height: 10, marginTop: 4 }} />
      </div>
    </>
  );
  return (
    <div className="themecards" style={{ marginTop: 12 }} role="radiogroup" aria-label="Theme">
      {(
        [
          ["light", "Light"],
          ["dark", "Dark"],
          ["system", "System"],
        ] as const
      ).map(([k, n]) => (
        <button key={k} className={`tcard ${S.prefs.theme === k ? "on" : ""}`} role="radio" aria-checked={S.prefs.theme === k} onClick={() => setPref("theme", k)}>
          <div className="tprev" style={k === "system" ? { gridTemplateColumns: "1fr 1fr", display: "grid" } : undefined}>
            {k === "system" ? (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "30% 1fr" }}>{pv(L)}</div>
                <div style={{ display: "grid", gridTemplateColumns: "30% 1fr" }}>{pv(Dk)}</div>
              </>
            ) : (
              pv(k === "light" ? L : Dk)
            )}
          </div>
          <span className="row" style={{ fontWeight: 500, fontSize: 13, gap: 6 }}>
            <Ic n={k === "light" ? "sun" : k === "dark" ? "moon" : "monitor"} s={14} />
            {n}
            {S.prefs.theme === k && (
              <>
                <span className="sp" />
                <span style={{ color: "var(--acc)" }}>
                  <Ic n="circle-check" s={15} />
                </span>
              </>
            )}
          </span>
        </button>
      ))}
    </div>
  );
}

function strength(pw: string) {
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[0-9]/.test(pw) && /[a-zA-Z]/.test(pw)) s++;
  if (/[^a-zA-Z0-9]/.test(pw)) s++;
  return s;
}
function StrengthMeter({ pw }: { pw: string }) {
  if (!pw) return null;
  const s = strength(pw);
  const c = ["var(--red)", "var(--red)", "var(--amber)", "var(--green)", "var(--green)"][s]!;
  const n = ["Too short", "Weak", "Fair", "Good", "Strong"][s];
  return (
    <div className="row" style={{ gap: 8 }}>
      <div className="strength grow" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <i key={i} className={i < s ? "on" : ""} style={css({ "--c": c })} />
        ))}
      </div>
      <span style={{ fontSize: 11.5, color: c, width: 60, textAlign: "right" }}>{n}</span>
    </div>
  );
}

/* ---------- sections ---------- */

function Workspace() {
  const d = D();
  const [name, setName] = useState(d.ws.name);
  const [url, setUrl] = useState(d.ws.url);
  const saveWs = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return toast("Give the workspace a name", { kind: "err" });
    mutate(() => Object.assign(d.ws, { name: name.trim(), url: url.trim() }));
    toast("Workspace saved");
  };
  return (
    <>
      <form onSubmit={saveWs}>
        <div className="sblock" style={{ marginTop: 0 }}>
          <div className="row" style={{ gap: 14, marginBottom: 18 }}>
            <WsLogo w={d.ws} px={52} />
            <div>
              <div className="label" style={{ marginBottom: 6 }}>
                Workspace icon
              </div>
              <div className="swatches">
                {["#2F2E2A", "#5A67D8", "#3B82C4", "#23918A", "#C54B78", "#C48A1E"].map((c) => (
                  <button key={c} type="button" className={`sw ${d.ws.c === c ? "on" : ""}`} style={css({ "--c": c, width: 22, height: 22 })} onClick={() => mutate(() => (d.ws.c = c))} aria-label={`Color ${c}`} />
                ))}
              </div>
            </div>
          </div>
          <div className="col" style={{ gap: 14, maxWidth: 440 }}>
            <div className="field">
              <label className="label" htmlFor="ws-name">
                Workspace name
              </label>
              <input className="input" id="ws-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label className="label" htmlFor="ws-url">
                Workspace URL
              </label>
              <div className="row" style={{ gap: 0 }}>
                <span className="input" style={{ width: "auto", background: "var(--surface-2)", borderRight: 0, borderRadius: "6px 0 0 6px", display: "flex", alignItems: "center", color: "var(--text-2)" }}>
                  dotrix.app/w/
                </span>
                <input className="input" id="ws-url" value={url} onChange={(e) => setUrl(e.target.value)} style={{ borderRadius: "0 6px 6px 0" }} />
              </div>
              <span className="hint">Changing the URL will break existing links.</span>
            </div>
            <div>
              <button className="btn btn-primary" type="submit">
                Save changes
              </button>
            </div>
          </div>
        </div>
      </form>
      {d.ws.kind === "personal" && (
        <div className="sblock">
          <h2>Turn into an organisation</h2>
          <SRow t="Work with a team" d="A personal workspace is just for you. An organisation can invite people; you get a new personal workspace.">
            <button className="btn btn-secondary" onClick={() => toast("Turned into an organisation")}>
              Turn into an organisation
            </button>
          </SRow>
        </div>
      )}
      <div className="sblock">
        <h2 style={{ color: "var(--red)" }}>Danger zone</h2>
        <SRow t="Delete workspace" d="Permanently delete this workspace, its projects, tasks, documents, and files. This cannot be undone.">
          <button className="btn btn-danger-ghost" style={{ border: "1px solid color-mix(in srgb,var(--red) 35%,transparent)" }} onClick={() => toast("Only the owner can delete the workspace, from the API for now", { kind: "info" })}>
            Delete workspace
          </button>
        </SRow>
      </div>
    </>
  );
}

function Agents() {
  const sel = D().agents.find((a) => a.handle === S.ui.agentSel);
  if (sel)
    return (
      <>
        <button className="btn btn-sm btn-ghost" onClick={() => ((S.ui.agentSel = null), render())} style={{ margin: "-4px 0 12px -8px" }}>
          <Ic n="arrow-left" s={14} />
          All agents
        </button>
        <div className="row" style={{ gap: 12, marginBottom: 16 }}>
          <span className="av lg" style={css({ "--c": sel.c })}>
            <Ic n={sel.icon} s={18} />
          </span>
          <div>
            <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>
              {sel.handle === "auto" ? "Auto" : `${sel.name} agent`} <span className="faint mono" style={{ fontSize: 12, fontWeight: 400 }}>@{sel.handle}</span>
            </h2>
            <div className="muted">{sel.desc}</div>
          </div>
          <span className="sp" />
          {sel.builtIn && <span className="badge">{sel.customised ? "Customised" : "Built-in"}</span>}
        </div>
        <SRow t="Model" d="Which model this agent uses; the project's model when unset.">
          <select className="select" style={{ width: "auto", minWidth: 180 }} value={sel.model ?? ""} onChange={(e) => mutate(() => ((sel.model = e.target.value || undefined), (sel.customised = true)))}>
            <option value="">Project default</option>
            {["Gemini 3.8 Flash", "Claude Sonnet 5.5", "Claude Opus 5.5", "GPT-5.5"].map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </SRow>
        <SRow t="Tools" d="From the catalogue. Writes always wait for approval unless an owner allows a low-risk action.">
          <span className="row" style={{ gap: 4, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {sel.tools.map((t) => (
              <span key={t} className="badge mono">
                {t}
              </span>
            ))}
          </span>
        </SRow>
        <SRow t="Comments and labels" d="Low-risk actions an owner may let this agent take without asking.">
          <select className="select" style={{ width: "auto" }} defaultValue="ask">
            <option value="ask">Ask first</option>
            <option value="allow">Allow</option>
            <option value="block">Block</option>
          </select>
        </SRow>
        <div className="sblock">
          <h2>Instructions</h2>
          <textarea className="textarea" rows={6} defaultValue={`You are the ${sel.name} agent. ${sel.desc}`} style={{ marginTop: 10 }} aria-label="Instructions" />
          <div className="row" style={{ marginTop: 10, gap: 6 }}>
            <button className="btn btn-primary" onClick={() => (mutate(() => (sel.customised = true)), toast("Saved as a new version"))}>
              Save
            </button>
            {sel.customised && (
              <button className="btn btn-secondary" onClick={() => (mutate(() => ((sel.customised = false), (sel.model = undefined))), toast("Reset to default"))}>
                Reset to default
              </button>
            )}
          </div>
        </div>
      </>
    );
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="muted" style={{ fontSize: 13 }}>
          {D().agents.length} agents · used by every project unless a project overrides one
        </span>
        <span className="sp" />
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => {
            const h = "agent" + (D().agents.length + 1);
            mutate(() => D().agents.push({ handle: h, name: "Custom", desc: "A custom agent.", icon: "bot", c: "#57544E", builtIn: false, tools: ["knowledge.read"] }));
            S.ui.agentSel = h;
            render();
          }}
        >
          <Ic n="plus" s={13} />
          New agent
        </button>
      </div>
      <div className="panel" style={{ overflow: "hidden" }}>
        {D().agents.map((a) => (
          <div key={a.handle} className="mini" style={{ minHeight: 52 }} onClick={() => ((S.ui.agentSel = a.handle), render())}>
            <span className="av md" style={css({ "--c": a.c })}>
              <Ic n={a.icon} s={13} />
            </span>
            <div className="grow" style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 500 }}>
                {a.handle === "auto" ? "Auto" : `${a.name} agent`} <span className="faint mono" style={{ fontSize: 11.5, fontWeight: 400 }}>@{a.handle}</span>
              </div>
              <div className="faint trunc" style={{ fontSize: 12 }}>
                {a.desc}
              </div>
            </div>
            <span className="badge">{!a.builtIn ? "Custom" : a.customised ? "Customised" : "Built-in"}</span>
            <Ic n="chevron-right" s={14} />
          </div>
        ))}
      </div>
    </>
  );
}

function Rules() {
  const [base, setBase] = useState("- Write in plain English.\n- Link issues by key (WEB-12).\n- Never promise dates the board doesn't support.");
  return (
    <>
      <div className="sblock" style={{ marginTop: 0 }}>
        <h2>Rules for every project</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Layered under each project's own <span className="mono">agent-rules/</span>, so a project's rules win.
        </p>
        <textarea className="textarea mono" rows={7} value={base} onChange={(e) => setBase(e.target.value)} style={{ fontSize: 12.5 }} aria-label="Workspace rules" />
        <div style={{ marginTop: 10 }}>
          <button className="btn btn-primary" onClick={() => toast("Rules saved (v4)")}>
            Save rules
          </button>
        </div>
      </div>
      <div className="sblock">
        <h2>Skills</h2>
        {[
          ["write-an-adr", "Write an architecture decision record"],
          ["triage-a-bug", "Turn a bug report into an issue with steps and severity"],
          ["break-down-a-feature", "Split a feature into an epic and stories"],
          ["scope-a-failing-build", "Find what a failing build touches"],
        ].map(([n, d]) => (
          <SRow
            key={n}
            t={
              <span className="row" style={{ gap: 6 }}>
                <Ic n="scroll-text" s={14} />
                <span className="mono">{n}</span>
              </span>
            }
            d={d}
          >
            <button className="btn btn-secondary btn-sm" onClick={() => toast("Skill editing opens here when the API is wired", { kind: "info" })}>
              Edit
            </button>
          </SRow>
        ))}
      </div>
    </>
  );
}

function Automations() {
  return (
    <>
      <div className="panel" style={{ overflow: "hidden" }}>
        {D().automations.length ? (
          D().automations.map((a) => {
            const p = proj(a.project);
            return (
              <div key={a.id} className="mini" style={{ minHeight: 56, cursor: "default", gap: 12 }}>
                <span className="ftype" style={css({ "--c": "var(--acc)" })}>
                  <Ic n="zap" s={14} />
                </span>
                <div className="grow" style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 500 }}>{a.name}</div>
                  <div className="faint trunc" style={{ fontSize: 12 }}>
                    {who(a.agent)?.name} · {a.trigger} · {p?.name}
                    {a.last ? ` · last ran ${ago(a.last)}` : ""}
                  </div>
                </div>
                <Tog on={a.enabled} set={(v) => mutate(() => (a.enabled = v))} label={`Turn ${a.name} on`} />
              </div>
            );
          })
        ) : (
          <Empty icon="zap" title="No automations" text="Let agents run on a schedule or when something happens." cls="sm" />
        )}
      </div>
      <div className="sblock">
        <h2>Presets</h2>
        {[
          ["Keep documents current", "After approved changes, Documentation proposes current-state and roadmap updates."],
          ["Flag stale documents", "Weekly, lists documents that may be out of date."],
          ["Triage new bugs", "When an issue is created, Auto checks for duplicates and fills in the fields."],
          ["Watch a topic", "Research re-checks a topic weekly and reports what changed."],
        ].map(([n, d]) => (
          <SRow key={n} t={n} d={d}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => {
                mutate(() => D().automations.push({ id: uid("am"), project: visibleProjects()[0]!.id, name: n!, agent: n!.startsWith("Watch") ? "research" : n!.startsWith("Triage") ? "auto" : "documentation", trigger: n!.startsWith("Triage") ? "When an issue is created" : "Weekly, Monday 08:00", enabled: true }));
                toast(`Added “${n}”`);
              }}
            >
              <Ic n="plus" s={13} />
              Add
            </button>
          </SRow>
        ))}
      </div>
    </>
  );
}

function GitHub() {
  const ps = visibleProjects();
  return (
    <>
      <div className="sblock" style={{ marginTop: 0 }}>
        <h2>Installations</h2>
        <SRow
          t={
            <span className="row" style={{ gap: 8 }}>
              <Ic n="github" s={15} />
              dotrix
            </span>
          }
          d="Organisation · 12 repositories · added by Tanjim Islam"
        >
          <button className="btn btn-secondary btn-sm" onClick={() => toast("Opens the app's settings on GitHub", { kind: "info" })}>
            Configure
          </button>
        </SRow>
        <div style={{ marginTop: 12 }}>
          <button className="btn btn-secondary" onClick={() => toast("Installing the GitHub App opens GitHub", { kind: "info" })}>
            <Ic n="plus" s={14} />
            Add a GitHub account
          </button>
        </div>
      </div>
      <div className="sblock">
        <h2>Connected repositories</h2>
        {ps.map((p) => (
          <SRow
            key={p.id}
            t={
              <span className="row" style={{ gap: 8 }}>
                <PIcon p={p} s={13} />
                {p.name}
              </span>
            }
            d={p.repo ? <span className="mono">{p.repo}</span> : "No repository"}
          >
            <button className="btn btn-secondary btn-sm" onClick={() => go("project", { id: p.key, tab: "overview" })}>
              {p.repo ? "Change" : "Connect"}
            </button>
          </SRow>
        ))}
      </div>
    </>
  );
}

function Audit() {
  return (
    <div className="panel" style={{ overflowX: "auto" }}>
      <table className="perm-t" style={{ minWidth: 560 }}>
        <thead>
          <tr>
            <th style={{ paddingLeft: 14, textAlign: "left" }}>When</th>
            <th style={{ textAlign: "left" }}>Who</th>
            <th style={{ textAlign: "left" }}>Action</th>
            <th style={{ textAlign: "left" }}>On</th>
          </tr>
        </thead>
        <tbody>
          {D().audit.map((a) => (
            <tr key={a.id}>
              <td style={{ paddingLeft: 14, textAlign: "left" }} className="muted">
                {ago(a.at)}
              </td>
              <td style={{ textAlign: "left" }}>
                <span className="row">
                  <Av id={a.by} cls="sm" tip={false} />
                  {who(a.by)?.name}
                </span>
              </td>
              <td style={{ textAlign: "left" }} className="mono">
                {a.action}
              </td>
              <td style={{ textAlign: "left" }}>
                {a.target}
                {a.project && <span className="faint"> · {proj(a.project)?.name}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Profile() {
  const [name, setName] = useState(S.prefs.name);
  const [title, setTitle] = useState(S.prefs.title);
  const err = !name.trim() ? "Enter your name" : "";
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (err) return;
        mutate(() => Object.assign(me()!, { name: name.trim(), title }));
        S.prefs.name = name.trim();
        S.prefs.title = title;
        save();
        toast("Profile saved");
      }}
      className="col"
      style={{ gap: 16, maxWidth: 440 }}
    >
      <div className="row" style={{ gap: 14 }}>
        <Av id={D().me} cls="xl" tip={false} />
        <div>
          <div className="label" style={{ marginBottom: 6 }}>
            Avatar color
          </div>
          <div className="swatches">
            {["#5A67D8", "#C54B78", "#3B82C4", "#23918A", "#C48A1E", "#8662C9"].map((c) => (
              <button key={c} type="button" className={`sw ${me()!.c === c ? "on" : ""}`} style={css({ "--c": c, width: 22, height: 22 })} onClick={() => mutate(() => (me()!.c = c))} aria-label="Color" />
            ))}
          </div>
        </div>
      </div>
      <div className="field">
        <label className="label" htmlFor="pf-name">
          Full name
        </label>
        <input className={`input ${err ? "is-error" : ""}`} id="pf-name" value={name} onChange={(e) => setName(e.target.value)} />
        {err && (
          <span className="err">
            <Ic n="circle-alert" s={12} />
            {err}
          </span>
        )}
      </div>
      <div className="field">
        <label className="label" htmlFor="pf-title">
          What you do
        </label>
        <input className="input" id="pf-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="field">
        <label className="label" htmlFor="pf-email">
          Email
        </label>
        <input className="input" id="pf-email" value={me()!.email} disabled />
        <span className="hint">Verified. Contact a workspace owner to change your sign-in email.</span>
      </div>
      <div className="sblock" style={{ marginTop: 4 }}>
        <h2>Sign-in methods</h2>
        <SRow t="Password" d="Set">
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => go("settings", { sec: "password" })}>
            Change
          </button>
        </SRow>
        <SRow
          t={
            <span className="row" style={{ gap: 6 }}>
              <Ic n="github" s={14} />
              GitHub
            </span>
          }
          d="Not linked"
        >
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => toast("Linking opens GitHub", { kind: "info" })}>
            Link
          </button>
        </SRow>
      </div>
      <div>
        <button className="btn btn-primary" type="submit">
          Save profile
        </button>
      </div>
    </form>
  );
}

function Password() {
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [conf, setConf] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (!cur) er.cur = "Enter your current password";
    if (pw.length < 10 || strength(pw) < 3) er.pw = "Use at least 10 characters with a number or symbol";
    if (pw !== conf) er.conf = "Passwords don't match";
    setErrs(er);
    if (Object.keys(er).length) return;
    setDone(true);
    setCur("");
    setPw("");
    setConf("");
  };
  const Err = ({ k }: { k: string }) =>
    errs[k] ? (
      <span className="err">
        <Ic n="circle-alert" s={12} />
        {errs[k]}
      </span>
    ) : null;
  return (
    <>
      {done && (
        <div className="alert ok" style={{ marginBottom: 14 }}>
          <Ic n="circle-check" s={15} />
          <span>Password updated. Your other browsers and apps were signed out.</span>
        </div>
      )}
      <form onSubmit={submit} className="col" style={{ gap: 14, maxWidth: 400 }}>
        <div className="field">
          <label className="label" htmlFor="pw-cur">
            Current password
          </label>
          <input type="password" className={`input ${errs.cur ? "is-error" : ""}`} id="pw-cur" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
          <Err k="cur" />
        </div>
        <div className="field">
          <label className="label" htmlFor="pw-new">
            New password
          </label>
          <input type="password" className={`input ${errs.pw ? "is-error" : ""}`} id="pw-new" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />
          <StrengthMeter pw={pw} />
          {errs.pw ? <Err k="pw" /> : <span className="hint">At least 10 characters with a number or symbol.</span>}
        </div>
        <div className="field">
          <label className="label" htmlFor="pw-conf">
            Confirm new password
          </label>
          <input type="password" className={`input ${errs.conf ? "is-error" : ""}`} id="pw-conf" autoComplete="new-password" value={conf} onChange={(e) => setConf(e.target.value)} />
          <Err k="conf" />
        </div>
        <div>
          <button className="btn btn-primary" type="submit">
            Update password
          </button>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start", marginLeft: -8 }} onClick={() => toast("We've emailed you a link", { kind: "info" })}>
          Forgot it? Email me a link
        </button>
      </form>
    </>
  );
}

function TwoFA() {
  const [setup, setSetup] = useState(false);
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  const d = D();
  if (d.tfa)
    return (
      <>
        <div className="alert ok">
          <Ic n="shield-check" s={16} />
          <div>
            <b>Two-factor authentication is on.</b>
            <div className="muted">You'll enter a code from your authenticator app when signing in on a new device.</div>
          </div>
        </div>
        <div className="sblock">
          <h2>Recovery codes</h2>
          <p className="muted" style={{ fontSize: 13 }}>
            Store these somewhere safe. Each code works once.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2,max-content)", gap: "6px 28px", fontFamily: "var(--mono)", fontSize: 13, padding: 14, border: "1px solid var(--border)", borderRadius: "var(--r)", background: "var(--sunken)", userSelect: "all" }}>
            {["7KQ2-M8PX", "D4TN-9WRE", "HV3C-QZ6L", "P2YB-J7SK", "R9FG-4NUD", "X6MA-T3HE"].map((c) => (
              <span key={c}>{c}</span>
            ))}
          </div>
          <div style={{ marginTop: 14 }}>
            <button className="btn btn-danger-ghost" onClick={() => (mutate(() => (d.tfa = false)), toast("Two-factor authentication is off"))}>
              Turn off two-factor authentication
            </button>
          </div>
        </div>
      </>
    );
  if (setup)
    return (
      <div className="panel" style={{ padding: 18, display: "flex", gap: 20, flexWrap: "wrap" }}>
        <div style={{ width: 132, height: 132, display: "grid", gridTemplateColumns: "repeat(11,1fr)", gap: 1, padding: 8, background: "#fff", borderRadius: 8, border: "1px solid var(--border)" }} aria-label="QR code">
          {Array.from({ length: 121 }, (_, i) => {
            const r = Math.floor(i / 11);
            const c = i % 11;
            const f = (r < 3 && c < 3) || (r < 3 && c > 7) || (r > 7 && c < 3);
            const on = f ? !((r === 1 && c === 1) || (r === 1 && c === 9) || (r === 9 && c === 1)) : (i * 7919) % 13 < 6;
            return <i key={i} style={{ background: on ? "#1D1C1A" : "#fff" }} />;
          })}
        </div>
        <div className="grow col" style={{ gap: 10, minWidth: 220 }}>
          <div>
            <b>1. Scan the QR code</b>
            <div className="muted" style={{ fontSize: 13 }}>
              Use 1Password, Authy, or Google Authenticator.
            </div>
          </div>
          <div>
            <b>2. Enter the 6-digit code</b>
          </div>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              if (!/^\d{6}$/.test(code)) return setErr("Enter the 6 digits from your app");
              mutate(() => (d.tfa = true));
              toast("Two-factor authentication is on");
            }}
          >
            <input className={`input mono ${err ? "is-error" : ""}`} inputMode="numeric" maxLength={6} placeholder="000000" style={{ width: 130, letterSpacing: ".2em", fontSize: 15 }} autoFocus value={code} onChange={(e) => setCode(e.target.value)} aria-label="Code" />
            <button className="btn btn-primary" type="submit">
              Verify
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setSetup(false)}>
              Cancel
            </button>
          </form>
          {err ? (
            <span className="err">
              <Ic n="circle-alert" s={12} />
              {err}
            </span>
          ) : (
            <span className="hint">Any 6 digits work on the seeded data.</span>
          )}
        </div>
      </div>
    );
  return (
    <div className="panel" style={{ padding: 18 }}>
      <div className="row" style={{ gap: 14, alignItems: "flex-start" }}>
        <span className="ftype" style={css({ "--c": "var(--amber)", width: 36, height: 36 })}>
          <Ic n="shield-alert" s={18} />
        </span>
        <div className="grow">
          <b>Two-factor authentication is off</b>
          <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
            Protect your account with a code from an authenticator app in addition to your password.
          </p>
          <button className="btn btn-primary" onClick={() => setSetup(true)}>
            Set up two-factor authentication
          </button>
        </div>
      </div>
    </div>
  );
}

function Plan() {
  const d = D();
  const plan = d.ws.plan || "Team";
  return (
    <>
      <div className="panel" style={{ padding: 18, marginBottom: 18 }}>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <div>
            <div className="eyebrow">Current plan</div>
            <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-.015em", marginTop: 4 }}>
              {plan}{" "}
              <span className="muted" style={{ fontSize: 14, fontWeight: 400 }}>
                · $12 per member / month
              </span>
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              Renews {fmtDate(dOff(7), true)} · Billed monthly
            </div>
          </div>
          <span className="sp" />
          <button className="btn btn-secondary" onClick={() => go("settings", { sec: "invoices" })}>
            View invoices
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 18, marginTop: 18 }}>
          {(
            [
              ["Members", d.members.length, 10, ""],
              ["Agent tokens this month", 3.1, 10, "M"],
              ["Projects", d.projects.length, 50, ""],
            ] as const
          ).map(([n, v, m, u]) => (
            <div key={n}>
              <div className="row" style={{ fontSize: 12.5, marginBottom: 6 }}>
                <span className="muted">{n}</span>
                <span className="sp" />
                <span className="num">
                  {v}
                  {u} of {m}
                  {u}
                </span>
              </div>
              <div className="meter">
                <i style={{ width: `${(v / m) * 100}%`, ...(v / m > 0.75 ? { background: "var(--amber)" } : {}) }} />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 12 }}>
        {(
          [
            ["Free", "$0", ["Up to 3 members", "Unlimited tasks", "Agents with your own key"]],
            ["Team", "$12", ["Up to 50 members", "Timelines & custom views", "Agents, 10M tokens a month", "Guest access"]],
            ["Business", "$24", ["Unlimited members", "Coding sessions", "SAML SSO", "Audit export"]],
          ] as const
        ).map(([n, pr, fs]) => {
          const cur = plan === n;
          return (
            <div key={n} className={`plan ${cur ? "cur" : ""}`}>
              <div className="row">
                <b>{n}</b>
                {cur && <span className="badge accent">Current</span>}
              </div>
              <div className="pr">
                {pr}
                <span className="muted" style={{ fontSize: 12.5, fontWeight: 400 }}>
                  {" "}
                  /member/mo
                </span>
              </div>
              <ul>
                {fs.map((f) => (
                  <li key={f}>
                    <Ic n="check" s={13} />
                    {f}
                  </li>
                ))}
              </ul>
              <div style={{ marginTop: 8 }}>
                {cur ? (
                  <button className="btn btn-secondary btn-block" disabled>
                    Current plan
                  </button>
                ) : (
                  <button className={`btn ${n === "Business" ? "btn-primary" : "btn-secondary"} btn-block`} onClick={() => (mutate(() => (d.ws.plan = n)), toast(`Switched to ${n}`))}>
                    {n === "Free" ? "Downgrade" : "Upgrade"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

function Body({ sec }: { sec: string }) {
  const d = D();
  const Pr = S.prefs;
  switch (sec) {
    case "workspace":
      return <Workspace />;
    case "appearance":
      return (
        <>
          <div className="sblock" style={{ marginTop: 0 }}>
            <h2>Theme</h2>
            <ThemeCards />
          </div>
          <div className="sblock">
            <h2>Accent color</h2>
            <SRow t="Accent" d="Used for primary buttons, focus rings, and selection.">
              <div className="swatches" role="radiogroup" aria-label="Accent color">
                {ACCENTS.map(([k, c]) => (
                  <button key={k} className={`sw ${Pr.accent === k ? "on" : ""}`} style={css({ "--c": c })} role="radio" aria-checked={Pr.accent === k} onClick={() => setPref("accent", k)} aria-label={k} data-tip={k[0]!.toUpperCase() + k.slice(1)}>
                    {Pr.accent === k && <Ic n="check" s={13} />}
                  </button>
                ))}
              </div>
            </SRow>
          </div>
          <div className="sblock">
            <h2>Density</h2>
            <SRow t="Sidebar density" d="Compact fits more projects on screen.">
              <Seg k="side" opts={["comfortable", "compact"]} />
            </SRow>
            <SRow t="Task display" d="Row height in lists and card padding on boards.">
              <Seg k="density" opts={["comfortable", "compact"]} />
            </SRow>
            <SRow t="Motion" d="Reduce animations for drawers, modals, and transitions.">
              <Sel
                k="motion"
                v={Pr.motion}
                opts={[
                  ["system", "Follow system"],
                  ["reduce", "Reduce motion"],
                ]}
              />
            </SRow>
          </div>
        </>
      );
    case "language":
      return (
        <>
          <SRow t="Language" d="The language used throughout the interface.">
            <Sel k="lang" v={Pr.lang} opts={["English (US)", "English (UK)", "Deutsch", "Español", "Français", "日本語"]} />
          </SRow>
          <SRow t="Spellcheck" d="Check spelling in descriptions and comments.">
            <PTog k="spell" />
          </SRow>
        </>
      );
    case "datetime":
      return (
        <>
          <SRow t="Time zone" d="Used for due dates and reminders.">
            <Sel k="tz" v={Pr.tz} opts={["(GMT-08:00) Pacific Time", "(GMT-07:00) Pacific Time", "(GMT-05:00) Eastern Time", "(GMT+00:00) London", "(GMT+01:00) Berlin", "(GMT+08:00) Singapore"]} />
          </SRow>
          <SRow
            t="Date format"
            d={
              <>
                Preview: <b>{fmtDate(dOff(8))}</b>
              </>
            }
          >
            <Sel
              k="dateFmt"
              v={Pr.dateFmt}
              opts={[
                ["MMM d", "Oct 1"],
                ["d/M", "1/10"],
                ["M/d", "10/1"],
                ["yyyy-MM-dd", "2026-10-01"],
              ]}
            />
          </SRow>
          <SRow t="Start week on" d="Affects calendars and the timeline.">
            <Sel
              k="weekStart"
              v={Pr.weekStart}
              opts={[
                ["1", "Monday"],
                ["0", "Sunday"],
                ["6", "Saturday"],
              ]}
            />
          </SRow>
          <SRow t="Time format">
            <Sel
              k="timeFmt"
              v={P().timeFmt ?? "12"}
              opts={[
                ["12", "12-hour (2:30 PM)"],
                ["24", "24-hour (14:30)"],
              ]}
            />
          </SRow>
        </>
      );
    case "members":
      return (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <button className="btn btn-primary" onClick={invite}>
              <Ic n="user-plus" s={14} />
              Invite member
            </button>
            <button className="btn btn-secondary" onClick={() => go("members")}>
              Open member directory
            </button>
          </div>
          <div className="panel" style={{ overflow: "hidden" }}>
            {d.members.map((m) => (
              <div key={m.id} className="mini" style={{ minHeight: 52, cursor: "default" }}>
                <Av id={m.id} cls="md" tip={false} />
                <div className="grow">
                  <div style={{ fontWeight: 500 }}>{m.name}</div>
                  <div className="faint" style={{ fontSize: 12 }}>
                    {m.email}
                  </div>
                </div>
                {m.status === "invited" && <span className="badge amber">Invited</span>}
                {m.role === "Owner" ? (
                  <span className="pillbtn">
                    <Ic n="crown" s={13} />
                    Owner
                  </span>
                ) : (
                  <button className="pillbtn bordered" onClick={(e) => openPop(e.currentTarget, "role", { id: m.id })}>
                    {m.role}
                    <Ic n="chevron-down" s={12} />
                  </button>
                )}
                <button className="ibtn ibtn-sm" onClick={(e) => openPop(e.currentTarget, "ctx", { ctx: "member", id: m.id })} aria-label="Options">
                  <Ic n="ellipsis" s={14} />
                </button>
              </div>
            ))}
          </div>
        </>
      );
    case "teams":
      return (
        <>
          <div style={{ marginBottom: 12 }}>
            <button className="btn btn-secondary btn-sm" onClick={newTeam}>
              <Ic n="plus" s={13} />
              New team
            </button>
          </div>
          <TeamsGrid />
        </>
      );
    case "projects": {
      const arch = d.projects.filter((p) => p.archived);
      return (
        <>
          <SRow t="Default project view" d="The tab that opens when you open a project.">
            <Sel
              k="defaultTab"
              v={P().defaultTab ?? "board"}
              opts={[
                ["board", "Board"],
                ["list", "List"],
                ["table", "Table"],
                ["overview", "Overview"],
                ["timeline", "Timeline"],
              ]}
            />
          </SRow>
          <SRow t="Show completed tasks on boards">
            <PTog k="showDoneBoard" />
          </SRow>
          <div className="sblock">
            <h2>Archived projects</h2>
            {arch.length ? (
              arch.map((p) => (
                <div key={p.id} className="srow">
                  <div className="row">
                    <PIcon p={p} s={14} />
                    <b style={{ fontWeight: 500 }}>{p.name}</b>
                  </div>
                  <div className="row">
                    <button className="btn btn-secondary btn-sm" onClick={() => restoreProject(p.id)}>
                      Restore
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <p className="faint" style={{ padding: "12px 0" }}>
                No archived projects. Archived projects are hidden from the sidebar but keep all their tasks.
              </p>
            )}
            <div style={{ marginTop: 12 }}>
              <button className="btn btn-secondary btn-sm" onClick={() => go("archive")}>
                <Ic n="archive" s={13} />
                Open archive
              </button>
            </div>
          </div>
        </>
      );
    }
    case "permissions":
      return (
        <>
          <SRow t="Members can create projects">
            <PTog k="permCreate" />
          </SRow>
          <SRow t="Members can invite guests" d="Guests only see projects they are added to.">
            <PTog k="permGuests" />
          </SRow>
          <div className="sblock">
            <h2>What members can do with the agents</h2>
            <p className="muted" style={{ fontSize: 13 }}>
              Off by default: a member's request that would change something waits for an owner or admin.
            </p>
            <SRow t="Edit documents" d="Change the project's knowledge directly.">
              <PTog k="mEditDocs" def={false} />
            </SRow>
            <SRow t="Approve agents' changes" d="Approve or reject what an agent proposes.">
              <PTog k="mApprove" def={false} />
            </SRow>
            <SRow t="Start coding" d="Ask Claude Code or Codex to work on a task.">
              <PTog k="mCoding" def={false} />
            </SRow>
            <SRow t="Choose the agents' model" d="Bigger models cost more.">
              <PTog k="mModel" def={false} />
            </SRow>
          </div>
          <div className="sblock">
            <h2>Role permissions</h2>
            <div style={{ marginTop: 12 }}>
              <PermsTable />
            </div>
          </div>
        </>
      );
    case "agents":
      return <Agents />;
    case "rules":
      return <Rules />;
    case "automations":
      return <Automations />;
    case "github":
      return <GitHub />;
    case "audit":
      return <Audit />;
    case "notif-email":
      return (
        <>
          <SRow t="Mentions" d="When someone @mentions you.">
            <NTog k="email_mention" />
          </SRow>
          <SRow t="Assignments" d="When a task is assigned to you.">
            <NTog k="email_assign" />
          </SRow>
          <SRow t="Comments" d="On tasks you created or are assigned.">
            <NTog k="email_comment" />
          </SRow>
          <SRow t="Agents' changes" d="When an agent's change waits for you, and when yours are decided.">
            <NTog k="email_approval" def />
          </SRow>
          <SRow t="Daily digest" d="A summary of what's unread, every weekday at 8:00.">
            <NTog k="email_digest" />
          </SRow>
        </>
      );
    case "notif-push":
      return (
        <>
          <SRow t="Mentions">
            <NTog k="push_mention" />
          </SRow>
          <SRow t="Assignments">
            <NTog k="push_assign" />
          </SRow>
          <SRow t="Comments">
            <NTog k="push_comment" />
          </SRow>
          <SRow t="Due date reminders" d="One day before a task is due.">
            <NTog k="push_due" />
          </SRow>
        </>
      );
    case "notif-mentions":
      return (
        <>
          <SRow t="@mentions in comments, chat, and descriptions">
            <NTog k="mention_all" />
          </SRow>
          <SRow t="@team mentions" d="When your team is mentioned, e.g. @Product.">
            <NTog k="mention_team" def />
          </SRow>
          <SRow t="@workspace mentions" d="Announcements to everyone.">
            <NTog k="mention_ws" />
          </SRow>
        </>
      );
    case "notif-assign":
      return (
        <>
          <SRow t="When I'm assigned a task">
            <NTog k="assign_self" />
          </SRow>
          <SRow t="When my task changes status">
            <NTog k="assign_status" def />
          </SRow>
          <SRow t="When my task is overdue">
            <NTog k="assign_over" def />
          </SRow>
          <SRow t="When I'm watching a task and it changes">
            <NTog k="watching" def />
          </SRow>
        </>
      );
    case "notif-agents":
      return (
        <>
          <SRow t="Changes waiting for approval" d="Always on: an agent's change never goes through without someone deciding.">
            <Tog on set={() => toast("Approvals always come through", { kind: "info" })} label="Approvals" />
          </SRow>
          <SRow t="Plans to steer" d="When an agent pauses before an expensive step.">
            <Tog on set={() => toast("Checkpoints always come through", { kind: "info" })} label="Checkpoints" />
          </SRow>
          <SRow t="Findings" d="When a review or research run finds something.">
            <NTog k="findings" def />
          </SRow>
          <SRow t="Decisions on my requests" d="When someone else approves or rejects a change you asked for.">
            <NTog k="decided" def />
          </SRow>
        </>
      );
    case "profile":
      return <Profile />;
    case "preferences":
      return (
        <>
          <SRow t="Open on launch" d="The page you see when dotrix opens.">
            <Sel
              k="home"
              v={Pr.home}
              opts={[
                ["home", "Home"],
                ["mytasks", "My Tasks"],
                ["inbox", "Inbox"],
                ["chat", "Chat"],
              ]}
            />
          </SRow>
          <SRow t="Open tasks in" d="Side panel keeps your place in the list.">
            <Sel
              k="openTasks"
              v={Pr.openTasks}
              opts={[
                ["drawer", "Side panel"],
                ["full", "Full page"],
              ]}
            />
          </SRow>
          <SRow t="Confirm before deleting tasks">
            <PTog k="confirmDel" />
          </SRow>
        </>
      );
    case "shortcuts":
      return (
        <>
          {SHORTCUTS.map(([g, list]) => (
            <div key={g} className="sblock" style={{ marginTop: 18 }}>
              <h2>{g}</h2>
              {list.map(([n, k]) => (
                <div key={n} className="srow" style={{ padding: "9px 0" }}>
                  <span>{n}</span>
                  <span className="row" style={{ gap: 4 }}>
                    {k.map((x, i) => (
                      <span key={i} className="row" style={{ gap: 4 }}>
                        {i > 0 && k[0] === "G" && (
                          <span className="faint" style={{ fontSize: 11 }}>
                            then
                          </span>
                        )}
                        <kbd>{x}</kbd>
                      </span>
                    ))}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </>
      );
    case "password":
      return <Password />;
    case "sessions":
      return (
        <>
          {d.sessions.map((s) => (
            <SRow
              key={s.id}
              t={
                <span className="row" style={{ gap: 8 }}>
                  <Ic n={s.dev.includes("iPhone") ? "smartphone" : "monitor"} s={15} />
                  {s.dev}
                  {s.cur && <span className="badge green">This device</span>}
                </span>
              }
              d={`${s.loc} · ${s.at}`}
            >
              {!s.cur && (
                <button className="btn btn-secondary btn-sm" onClick={() => (mutate(() => (d.sessions = d.sessions.filter((x) => x !== s))), toast("Signed out"))}>
                  Sign out
                </button>
              )}
            </SRow>
          ))}
          <div style={{ marginTop: 16 }}>
            <button className="btn btn-danger-ghost" disabled={d.sessions.length < 2} onClick={() => (mutate(() => (d.sessions = d.sessions.filter((x) => x.cur))), toast("Signed out of all other sessions"))}>
              Sign out of all other sessions
            </button>
          </div>
        </>
      );
    case "devices":
      return (
        <>
          <div className="sblock" style={{ marginTop: 0 }}>
            <h2>Connect the CLI</h2>
            <p className="muted" style={{ fontSize: 13 }}>
              The <span className="mono">pmagent</span> CLI and its MCP server let Claude Code and Codex work your board from a local checkout.
            </p>
            {["uv tool install pmagent", "pmagent login", "pmagent connect"].map((c) => (
              <div key={c} className="row" style={{ gap: 8, marginTop: 6 }}>
                <code className="mono grow" style={{ padding: "6px 10px", background: "var(--surface-2)", borderRadius: "var(--r-sm)", fontSize: 12.5 }}>
                  {c}
                </code>
                <button className="ibtn ibtn-sm" onClick={() => void copy(c, "Command copied")} aria-label={`Copy ${c}`}>
                  <Ic n="copy" s={14} />
                </button>
              </div>
            ))}
          </div>
          <div className="sblock">
            <h2>Signed-in devices and tokens</h2>
            {[
              ["terminal", "pmagent CLI on MacBook Pro", "Device login · last used 2 hours ago"],
              ["key-round", "CI token (pmat_…7f3a)", "Personal access token · created Sep 12 · last used yesterday"],
            ].map(([i, t, dd]) => (
              <SRow
                key={t}
                t={
                  <span className="row" style={{ gap: 8 }}>
                    <Ic n={i!} s={15} />
                    {t}
                  </span>
                }
                d={dd}
              >
                <button className="btn btn-secondary btn-sm" onClick={() => toast("Revoked")}>
                  Revoke
                </button>
              </SRow>
            ))}
          </div>
        </>
      );
    case "2fa":
      return <TwoFA />;
    case "plan":
      return <Plan />;
    case "payment":
      return (
        <>
          <SRow
            t={
              <span className="row" style={{ gap: 10 }}>
                <span className="ftype" style={css({ "--c": "var(--blue)" })}>
                  <Ic n="credit-card" s={15} />
                </span>
                Visa ending in 4242
              </span>
            }
            d="Expires 08/2028 · Default"
          >
            <button className="btn btn-secondary btn-sm" onClick={() => toast("Card updates open in a secure payment window", { kind: "info" })}>
              Update
            </button>
          </SRow>
          <SRow t="Billing email" d="Invoices and receipts are sent here.">
            <span className="muted" style={{ userSelect: "all" }}>
              {me()!.email}
            </span>
          </SRow>
          <SRow t="Billing address" d="2150 Mission St, San Francisco, CA 94110">
            <button className="btn btn-secondary btn-sm" onClick={() => toast("Address editing opens in the billing portal", { kind: "info" })}>
              Edit
            </button>
          </SRow>
          <SRow t="Tax ID" d="Shown on invoices">
            <span className="muted">US EIN ••-•••4410</span>
          </SRow>
        </>
      );
    case "invoices":
      return (
        <div className="panel" style={{ overflowX: "auto" }}>
          <table className="perm-t" style={{ minWidth: 480 }}>
            <thead>
              <tr>
                <th style={{ paddingLeft: 14 }}>Invoice</th>
                <th style={{ textAlign: "left" }}>Date</th>
                <th style={{ textAlign: "left" }}>Amount</th>
                <th style={{ textAlign: "left" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {d.invoices.map((i) => (
                <tr key={i.id}>
                  <td style={{ paddingLeft: 14 }} className="mono">
                    {i.id}
                  </td>
                  <td style={{ textAlign: "left" }} className="num">
                    {fmtDate(i.date, true)}
                  </td>
                  <td style={{ textAlign: "left" }} className="num">
                    {i.amt}
                  </td>
                  <td style={{ textAlign: "left" }}>
                    <span className="badge green">
                      <Ic n="check" s={11} />
                      {i.st}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
  }
  return <Empty icon="file-question" title="Page not found" text="That settings page doesn't exist." />;
}

const LEADS: Record<string, string> = {
  workspace: "Your workspace name, address, and identity.",
  appearance: "Customize how dotrix looks on this device.",
  language: "Language and regional formats.",
  datetime: "How dates and times appear across the workspace.",
  members: `people have access to this workspace.`,
  teams: "Teams group people and projects.",
  projects: "Defaults for new projects and archived work.",
  permissions: "Control what each role can do.",
  agents: "The agents every project uses: what they may do, their model, and their instructions. Versioned and audited.",
  rules: "Rules every agent follows, and skills they can use, across every project.",
  automations: "Agents that run on a schedule or when something happens. Their changes still wait for approval.",
  github: "The GitHub App's installations, and the repository each project reads code from.",
  audit: "Everything people and agents changed, who asked, and who approved.",
  "notif-email": "Choose which emails you receive.",
  "notif-push": "Notifications on desktop and mobile.",
  "notif-mentions": "Decide which mentions reach you.",
  "notif-assign": "Updates about tasks assigned to you.",
  "notif-agents": "What the agents tell you about.",
  profile: "How you appear to others in the workspace.",
  preferences: "Personal defaults for how you work.",
  shortcuts: "Move faster with the keyboard.",
  password: "Use a long password you don't use anywhere else.",
  sessions: "Browsers and apps currently signed in to your account.",
  devices: "The CLI and the tokens that act as you.",
  "2fa": "Add a second step when signing in.",
  plan: "Your subscription and usage.",
  payment: "Payment method and billing details.",
  invoices: "Past invoices for this workspace.",
};

export function Settings() {
  const { params } = useRoute();
  const sec = params.sec || S.ui.settings || "profile";
  const admin = ["Owner", "Admin"].includes(me()!.role);
  const title = SET_NAV.flatMap((g) => g[1]).find((x) => x[0] === sec);
  const lead = sec === "members" ? `${D().members.length} ${LEADS.members}` : LEADS[sec];
  return (
    <div className="set">
      <nav className="set-nav" aria-label="Settings">
        {SET_NAV.filter(([, , adminOnly]) => !adminOnly || admin).map(([g, items]) => (
          <div key={g} style={{ display: "contents" }}>
            <div className="gh">{g}</div>
            {items.map(([k, n, i]) => (
              <button key={k} className={`sitem ${sec === k ? "on" : ""}`} onClick={() => ((S.ui.settings = k), (S.ui.agentSel = null), go("settings", { sec: k }))}>
                <Ic n={i} s={15} />
                <span>{n}</span>
              </button>
            ))}
          </div>
        ))}
      </nav>
      <div className="set-body">
        <div className="set-in" key={sec}>
          {title && (
            <>
              <h1>{title[1]}</h1>
              <p className="lead">{lead}</p>
            </>
          )}
          <Body sec={sec} />
        </div>
      </div>
    </div>
  );
}
