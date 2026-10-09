// Gr8r's settings (gr8r-studio/src/pages/settings.js): a left nav of sections, each a set of rows.
// dotrix adds the agents' sections (owners and admins): Agents, Rules and skills, Automations,
// GitHub, What members can do, Audit log; and Devices and tokens (the CLI) under Security.
import { useState, type CSSProperties, type ReactNode } from "react";

import { copy, openPop, setPref } from "../core/actions";
import { Ic, WsLogo } from "../core/icons";
import { confirmDlg, invite, newTeam, promptDlg } from "../core/more";
import { go, useRoute } from "../core/nav";
import { ago, dOff, fmtDate, uid } from "../core/utils";
import { ApiError } from "@/lib/api";

import {
  GRANTABLE,
  agentCatalog,
  agentDetail,
  agentReset,
  agentSaved,
  convertedToOrganization,
  fieldsOf,
  githubRepos,
  githubStatus,
  installGitHub,
  installationRemoved,
  linkGitHub,
  memberPermissionsSaved,
  models,
  notifSettings,
  notifSettingsSaved,
  otherSessionsSignedOut,
  passwordChanged,
  passwordResetRequested,
  profileSaved,
  repoConnected,
  ruleSaved,
  rules,
  sessionSignedOut,
  sessions,
  signInMethods,
  skillSaved,
  skills,
  tokenCreated,
  tokenRevoked,
  tokens,
  unlinkGitHub,
  useApi,
  workspaceRenamed,
  type AgentFields,
  type NotifSettings,
} from "../data/account";
import { automationAdded, automationToggled, isLive, live, reloadAgents } from "../data/live";
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
    if (isLive()) {
      const was = d.ws.name;
      mutate(() => (d.ws.name = name.trim()));
      workspaceRenamed(name.trim())
        .then(() => toast("Workspace saved"))
        .catch((er: unknown) => {
          mutate(() => (d.ws.name = was));
          setName(was);
          toast(`The workspace didn't save: ${errText(er)}`, { kind: "err" });
        });
      return;
    }
    mutate(() => Object.assign(d.ws, { name: name.trim(), url: url.trim() }));
    toast("Workspace saved");
  };
  const convert = () => {
    if (!isLive()) return toast("Turned into an organisation");
    confirmDlg({
      title: "Turn into an organisation?",
      body: "This workspace and its projects become an organisation that can invite people. You get a new, empty personal workspace.",
      ok: "Turn into an organisation",
      icon: "building-2",
      run: () => {
        convertedToOrganization(null)
          .then(() => toast("It's an organisation now: invite people from Members"))
          .catch((er: unknown) => toast(`It didn't change: ${errText(er)}`, { kind: "err" }));
      },
    });
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
                <input className="input" id="ws-url" value={url} onChange={(e) => setUrl(e.target.value)} style={{ borderRadius: "0 6px 6px 0" }} disabled={isLive()} />
              </div>
              <span className="hint">{isLive() ? "The address is fixed when the workspace is created." : "Changing the URL will break existing links."}</span>
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
            <button className="btn btn-secondary" onClick={convert} disabled={isLive() && live.ws?.role !== "owner"}>
              Turn into an organisation
            </button>
          </SRow>
        </div>
      )}
      <div className="sblock">
        <h2 style={{ color: "var(--red)" }}>Danger zone</h2>
        <SRow t="Delete workspace" d="Permanently delete this workspace, its projects, tasks, documents, and files. This cannot be undone.">
          <button className="btn btn-danger-ghost" style={{ border: "1px solid color-mix(in srgb,var(--red) 35%,transparent)" }} onClick={() => toast("Deleting a workspace isn't available yet", { kind: "info" })}>
            Delete workspace
          </button>
        </SRow>
      </div>
    </>
  );
}

const errText = (e: unknown) => (e instanceof Error && e.message ? e.message : "try again");

/** An agent's contract in a real workspace: loaded from the API, saved as a new version. */
function LiveAgent({ handle }: { handle: string }) {
  const a = useApi(() => agentDetail(handle), [handle]);
  const cat = useApi(agentCatalog);
  const ms = useApi(models);
  const [f, setF] = useState<AgentFields | null>(null);
  const [busy, setBusy] = useState(false);
  const owner = live.ws?.role === "owner";
  const back = () => ((S.ui.agentSel = null), render());
  if (a.error) return <div className="alert danger">{a.error}</div>;
  if (!a.data || !cat.data) return <div className="faint">Loading…</div>;
  const ag = a.data;
  const v = f ?? fieldsOf(ag);
  const set = (patch: Partial<AgentFields>) => setF({ ...v, ...patch });
  const look = D().agents.find((x) => x.handle === handle);
  const save = () => {
    if (!v.instructions.trim()) return toast("Give the agent instructions", { kind: "err" });
    setBusy(true);
    agentSaved(handle, v, ag.version ?? null)
      .then(async (r) => {
        toast(`Saved as version ${r.version ?? 1}`);
        setF(null);
        a.reload();
        await reloadAgents();
      })
      .catch((e: unknown) => toast(`${v.name} didn't save: ${errText(e)}`, { kind: "err", ms: 6000 }))
      .finally(() => setBusy(false));
  };
  const reset = () =>
    confirmDlg({
      title: ag.source === "custom" ? `Delete ${ag.name}?` : `Reset ${ag.name} to its default?`,
      body: ag.source === "custom" ? "Projects stop using it. Its history is kept in the audit log." : "Your changes to its contract are replaced by the built-in one. Its history is kept.",
      ok: ag.source === "custom" ? "Delete agent" : "Reset to default",
      danger: ag.source === "custom",
      icon: ag.source === "custom" ? "trash-2" : "rotate-ccw",
      run: () => {
        agentReset(handle)
          .then(async () => {
            toast(ag.source === "custom" ? "Agent deleted" : "Reset to default");
            setF(null);
            await reloadAgents();
            if (ag.source === "custom") back();
            else a.reload();
          })
          .catch((e: unknown) => toast(`It didn't change: ${errText(e)}`, { kind: "err" }));
      },
    });
  const toggleTool = (id: string) => set({ tools: v.tools.includes(id) ? v.tools.filter((t) => t !== id) : [...v.tools, id] });
  return (
    <>
      <button className="btn btn-sm btn-ghost" onClick={back} style={{ margin: "-4px 0 12px -8px" }}>
        <Ic n="arrow-left" s={14} />
        All agents
      </button>
      <div className="row" style={{ gap: 12, marginBottom: 16 }}>
        <span className="av lg" style={css({ "--c": look?.c ?? "#57544E" })}>
          <Ic n={look?.icon ?? "bot"} s={18} />
        </span>
        <div className="grow" style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>
            {handle === "auto" ? "Auto" : ag.name} <span className="faint mono" style={{ fontSize: 12, fontWeight: 400 }}>@{handle}</span>
          </h2>
          <div className="muted">{ag.description}</div>
        </div>
        <span className="badge">{ag.source === "custom" ? "Custom" : ag.source === "customised" ? "Customised" : "Built-in"}</span>
        {ag.version != null && <span className="badge mono">v{ag.version}</span>}
      </div>
      <SRow t="Name">
        <input className="input" style={{ width: 220 }} value={v.name} onChange={(e) => set({ name: e.target.value })} aria-label="Name" />
      </SRow>
      <SRow t="Description" d="One line, shown in Chat's agent picker.">
        <input className="input" style={{ width: 320 }} value={v.description} onChange={(e) => set({ description: e.target.value })} aria-label="Description" />
      </SRow>
      <SRow t="Model" d="Which model this agent uses; the run's model when unset.">
        <select className="select" style={{ width: "auto", minWidth: 180 }} value={v.model ?? ""} onChange={(e) => set({ model: e.target.value || null })} aria-label="Model">
          <option value="">The run's model</option>
          {(ms.data ?? []).map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
          {v.model && !(ms.data ?? []).some((m) => m.id === v.model) && <option value={v.model}>{v.model}</option>}
        </select>
      </SRow>
      <SRow t="Token budget" d="Tokens one run it leads may use; empty uses the project's.">
        <input
          className="input"
          inputMode="numeric"
          style={{ width: 140 }}
          value={v.budget_tokens ?? ""}
          onChange={(e) => {
            const n = Number.parseInt(e.target.value.replace(/\D/g, ""), 10);
            set({ budget_tokens: Number.isFinite(n) ? n : null });
          }}
          aria-label="Token budget"
        />
      </SRow>
      <div className="sblock">
        <h2>Tools</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          From the catalogue. Writes always wait for approval unless an owner allows a low-risk action.
        </p>
        {cat.data.tools.map((t) => (
          <SRow key={t.id} t={t.label} d={t.description}>
            <Tog on={v.tools.includes(t.id)} set={() => toggleTool(t.id)} label={t.label} />
          </SRow>
        ))}
      </div>
      <div className="sblock">
        <h2>Without asking</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Low-risk actions only. Only owners can allow one; every other write waits for approval.
        </p>
        {cat.data.low_risk_actions.map((act) => (
          <SRow key={act} t={act === "issues.comment" ? "Comment on issues" : act === "graph.link" ? "Link things in the graph" : act}>
            <select
              className="select"
              style={{ width: "auto" }}
              value={v.autonomy?.[act] ?? "ask"}
              onChange={(e) => set({ autonomy: { ...v.autonomy, [act]: e.target.value as "allow" | "ask" | "block" } })}
              aria-label={act}
            >
              <option value="ask">Ask first</option>
              <option value="allow" disabled={!owner}>
                Allow
              </option>
              <option value="block">Block</option>
            </select>
          </SRow>
        ))}
      </div>
      <div className="sblock">
        <h2>Instructions</h2>
        <textarea className="textarea" rows={10} value={v.instructions} onChange={(e) => set({ instructions: e.target.value })} style={{ marginTop: 10 }} aria-label="Instructions" />
        <div className="row" style={{ marginTop: 10, gap: 6 }}>
          <button className="btn btn-primary" onClick={save} disabled={busy || !f}>
            Save
          </button>
          {f && (
            <button className="btn btn-ghost" onClick={() => setF(null)}>
              Discard
            </button>
          )}
          <span className="sp" />
          {ag.source !== "built_in" && (
            <button className={`btn ${ag.source === "custom" ? "btn-danger-ghost" : "btn-secondary"}`} onClick={reset}>
              {ag.source === "custom" ? "Delete agent" : "Reset to default"}
            </button>
          )}
        </div>
      </div>
    </>
  );
}

/** A new custom agent in a real workspace: a name and handle, then its page. */
function newLiveAgent() {
  promptDlg({
    title: "New agent",
    label: "Name",
    value: "",
    run: (name: string) => {
      const n = name.trim();
      if (!n) return;
      const handle = n.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").replace(/-agent$/, "").slice(0, 30) || "custom";
      const body: AgentFields = {
        name: n,
        description: "",
        instructions: `You are the ${n} agent. Describe what it does, what it reads, and what it returns.`,
        model: null,
        budget_tokens: null,
        tools: ["knowledge.read", "knowledge.search", "board.read"],
        access: {},
        issue_types: [],
        can_call: [],
        autonomy: {},
        output: null,
        pipeline: null,
        triggers: [],
      };
      agentSaved(/^[a-z]/.test(handle) && handle.length > 1 ? handle : `a-${handle}`, body, null)
        .then(async (r) => {
          await reloadAgents();
          S.ui.agentSel = r.handle;
          render();
          toast(`Created @${r.handle}`);
        })
        .catch((e: unknown) => toast(`The agent wasn't created: ${errText(e)}`, { kind: "err", ms: 6000 }));
    },
  });
}

function Agents() {
  const sel = D().agents.find((a) => a.handle === S.ui.agentSel);
  if (sel && isLive()) return <LiveAgent handle={sel.handle} />;
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
            if (isLive()) return newLiveAgent();
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

/** One workspace rule or skill: edited in place, saved as a new version over the one it was based on. */
function VersionedText({ title, content, version, save, rows = 7 }: { title: string; content: string; version: number; save: (text: string, base: number) => Promise<{ version: number }>; rows?: number }) {
  const [text, setText] = useState(content);
  const [ver, setVer] = useState(version);
  const [busy, setBusy] = useState(false);
  const changed = text !== content;
  return (
    <>
      <textarea className="textarea mono" rows={rows} value={text} onChange={(e) => setText(e.target.value)} style={{ fontSize: 12.5 }} aria-label={title} />
      <div className="row" style={{ marginTop: 10, gap: 6 }}>
        <button
          className="btn btn-primary"
          disabled={busy || !changed}
          onClick={() => {
            setBusy(true);
            save(text, ver)
              .then((r) => {
                setVer(r.version);
                toast(`${title} saved (v${r.version})`);
              })
              .catch((e: unknown) => toast(`${title} didn't save: ${errText(e)}`, { kind: "err", ms: 6000 }))
              .finally(() => setBusy(false));
          }}
        >
          Save
        </button>
        {ver > 0 && <span className="faint mono" style={{ fontSize: 12 }}>v{ver}</span>}
      </div>
    </>
  );
}

function LiveRules() {
  const r = useApi(rules);
  const sk = useApi(skills);
  const [open, setOpen] = useState<string | null>(null);
  if (r.error || sk.error) return <div className="alert danger">{r.error || sk.error}</div>;
  if (!r.data || !sk.data) return <div className="faint">Loading…</div>;
  const base = r.data.find((x) => x.handle === "base");
  return (
    <>
      <div className="sblock" style={{ marginTop: 0 }}>
        <h2>Rules for every project</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Layered under each project's own <span className="mono">agent-rules/</span>, so a project's rules win.
        </p>
        <VersionedText title="Rules" content={base?.content ?? ""} version={base?.version ?? 0} save={(t, b) => ruleSaved("base", t, b).then((x) => (r.reload(), x))} />
      </div>
      <div className="sblock">
        <h2>Skills</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Procedures every project's agents can read when the work calls for one. A project's own skill of the same name wins.
        </p>
        {sk.data.map((x) => (
          <div key={x.name}>
            <SRow
              t={
                <span className="row" style={{ gap: 6 }}>
                  <Ic n="scroll-text" s={14} />
                  <span className="mono">{x.name}</span>
                </span>
              }
              d={x.description}
            >
              <button className="btn btn-secondary btn-sm" onClick={() => setOpen(open === x.name ? null : x.name)}>
                {open === x.name ? "Close" : "Edit"}
              </button>
            </SRow>
            {open === x.name && (
              <div style={{ padding: "4px 0 14px" }}>
                <VersionedText title={x.name} content={x.content} version={x.version} rows={12} save={(t, b) => skillSaved(x.name, t, b).then((y) => (sk.reload(), y))} />
              </div>
            )}
          </div>
        ))}
        {!sk.data.length && <p className="faint">No workspace skills yet. Each project starts with its own in agent-rules/skills/.</p>}
        <div style={{ marginTop: 12 }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() =>
              promptDlg({
                title: "New skill",
                label: "Name (lowercase, with dashes)",
                value: "",
                run: (v: string) => {
                  const name = v.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
                  if (!name) return;
                  skillSaved(name, `Description: what this skill is for.\n\n1. The first step.\n2. The next.`, 0)
                    .then(() => (sk.reload(), setOpen(name), toast(`Added ${name}: describe its steps`)))
                    .catch((e: unknown) => toast(`The skill wasn't added: ${errText(e)}`, { kind: "err" }));
                },
              })
            }
          >
            <Ic n="plus" s={13} />
            New skill
          </button>
        </div>
      </div>
    </>
  );
}

const Rules = () => (isLive() ? <LiveRules /> : <SeedRules />);
function SeedRules() {
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
                <Tog
                  on={a.enabled}
                  set={(v) => {
                    mutate(() => (a.enabled = v));
                    automationToggled(a);
                  }}
                  label={`Turn ${a.name} on`}
                />
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
                if (isLive()) {
                  void automationAdded(visibleProjects()[0]!.id, n!);
                  return;
                }
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

function LiveGitHub() {
  const st = useApi(githubStatus);
  const repos = useApi(githubRepos);
  const [busy, setBusy] = useState("");
  const admin = ["owner", "admin"].includes(live.ws?.role ?? "");
  if (st.error) return <div className="alert danger">{st.error}</div>;
  if (!st.data) return <div className="faint">Loading…</div>;
  const s = st.data;
  const byProject = new Map((repos.data ?? []).filter((r) => r.project_key).map((r) => [r.project_key!, r]));
  const connect = (pid: string, key: string, id: string) => {
    const r = id ? (repos.data ?? []).find((x) => `${x.installation_ref}:${x.github_repo_id}` === id) ?? null : null;
    setBusy(key);
    repoConnected(pid, r)
      .then((made) => {
        const p = proj(pid);
        if (p) p.repo = made?.html_url ?? undefined;
        toast(r ? `${key} reads ${r.full_name}` : `${key} has no repository now`);
        repos.reload();
      })
      .catch((e: unknown) => toast(`The repository didn't change: ${errText(e)}`, { kind: "err", ms: 6000 }))
      .finally(() => setBusy(""));
  };
  if (!s.configured)
    return (
      <div className="alert info">
        <Ic n="info" s={15} />
        <span>The GitHub App isn't set up on this server yet. Its owner registers it and adds its keys; then connect accounts here.</span>
      </div>
    );
  return (
    <>
      <div className="sblock" style={{ marginTop: 0 }}>
        <h2>Installations</h2>
        {s.installations.map((i) => (
          <SRow
            key={i.id}
            t={
              <span className="row" style={{ gap: 8 }}>
                <Ic n="github" s={15} />
                {i.account_login}
                {i.suspended && <span className="badge amber">Suspended</span>}
              </span>
            }
            d={`${i.account_type === "Organization" ? "Organisation" : "Personal account"} · added ${fmtDate(i.created_at.slice(0, 10), true)}`}
          >
            {admin && (
              <button
                className="btn btn-secondary btn-sm"
                onClick={() =>
                  confirmDlg({
                    title: `Remove ${i.account_login}?`,
                    body: "Projects with a repository from this account lose it. The app stays installed on GitHub until you uninstall it there.",
                    ok: "Remove",
                    danger: true,
                    icon: "github",
                    run: () => {
                      installationRemoved(i.id)
                        .then(() => (st.reload(), repos.reload(), toast(`Removed ${i.account_login}`)))
                        .catch((e: unknown) => toast(`It wasn't removed: ${errText(e)}`, { kind: "err" }));
                    },
                  })
                }
              >
                Remove
              </button>
            )}
          </SRow>
        ))}
        {!s.installations.length && <p className="faint">No GitHub accounts yet. Install the app on an account to connect its repositories, private ones too.</p>}
        {admin && s.install_url && (
          <div style={{ marginTop: 12 }}>
            <button className="btn btn-secondary" onClick={() => installGitHub(s)}>
              <Ic n="plus" s={14} />
              Add a GitHub account
            </button>
          </div>
        )}
      </div>
      <div className="sblock">
        <h2>Connected repositories</h2>
        {visibleProjects().map((p) => {
          const cur = byProject.get(p.key);
          return (
            <SRow
              key={p.id}
              t={
                <span className="row" style={{ gap: 8 }}>
                  <PIcon p={p} s={13} />
                  {p.name}
                </span>
              }
              d={cur ? <span className="mono">{cur.full_name}</span> : p.repo ? <span className="mono">{p.repo}</span> : "No repository"}
            >
              <select
                className="select"
                style={{ width: "auto", minWidth: 200 }}
                value={cur ? `${cur.installation_ref}:${cur.github_repo_id}` : ""}
                disabled={!admin || busy === p.key || !repos.data}
                onChange={(e) => connect(p.id, p.key, e.target.value)}
                aria-label={`Repository for ${p.name}`}
              >
                <option value="">No repository</option>
                {(repos.data ?? [])
                  .filter((r) => !r.project_key || r.project_key === p.key)
                  .map((r) => (
                    <option key={`${r.installation_ref}:${r.github_repo_id}`} value={`${r.installation_ref}:${r.github_repo_id}`}>
                      {r.full_name}
                      {r.private ? " (private)" : ""}
                    </option>
                  ))}
              </select>
            </SRow>
          );
        })}
      </div>
    </>
  );
}

function GitHub() {
  if (isLive()) return <LiveGitHub />;
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
  const methods = useApi(signInMethods);
  const err = !name.trim() ? "Enter your name" : "";
  const gh = methods.data?.accounts.find((a) => a.provider === "github");
  const keep = () => {
    mutate(() => Object.assign(me()!, { name: name.trim(), title }));
    S.prefs.name = name.trim();
    S.prefs.title = title;
    save();
  };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (err) return;
        if (isLive())
          return void profileSaved(name.trim(), title.trim())
            .then(() => (keep(), toast("Profile saved")))
            .catch((er: unknown) => toast(`Your profile didn't save: ${errText(er)}`, { kind: "err" }));
        keep();
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
        <SRow t="Password" d={!isLive() || methods.data?.password ? "Set" : "Not set: you sign in with an email link or GitHub"}>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => go("settings", { sec: "password" })}>
            {!isLive() || methods.data?.password ? "Change" : "Set one"}
          </button>
        </SRow>
        <SRow
          t={
            <span className="row" style={{ gap: 6 }}>
              <Ic n="github" s={14} />
              GitHub
            </span>
          }
          d={gh ? `Linked${gh.login ? ` as ${gh.login}` : ""}` : "Not linked"}
        >
          {gh ? (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() =>
                unlinkGitHub()
                  .then(() => (methods.reload(), toast("GitHub unlinked")))
                  .catch((er: unknown) => toast(`GitHub stays linked: ${errText(er)}`, { kind: "err", ms: 6000 }))
              }
            >
              Unlink
            </button>
          ) : (
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => (isLive() ? linkGitHub() : toast("Linking opens GitHub", { kind: "info" }))}>
              Link
            </button>
          )}
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
  const [busy, setBusy] = useState(false);
  const methods = useApi(signInMethods);
  // Signed in with an email link or GitHub only: a first password needs no current one.
  const hasPassword = !isLive() || methods.data?.password !== false;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const er: Record<string, string> = {};
    if (hasPassword && !cur) er.cur = "Enter your current password";
    if (pw.length < 10 || strength(pw) < 3) er.pw = "Use at least 10 characters with a number or symbol";
    if (pw !== conf) er.conf = "Passwords don't match";
    setErrs(er);
    if (Object.keys(er).length) return;
    const finish = () => {
      setDone(true);
      setCur("");
      setPw("");
      setConf("");
    };
    if (!isLive()) return finish();
    setBusy(true);
    passwordChanged(hasPassword ? cur : null, pw)
      .then(() => (finish(), methods.reload()))
      .catch((x: unknown) => {
        const wrong = x instanceof ApiError && Boolean(x.problem?.type?.endsWith("/wrong_password"));
        setErrs(wrong ? { cur: "That isn't your current password" } : { pw: errText(x) });
      })
      .finally(() => setBusy(false));
  };
  const forgot = () => {
    if (!isLive()) return toast("We've emailed you a link", { kind: "info" });
    passwordResetRequested(me()!.email)
      .then(() => toast(`We've emailed a link to ${me()!.email}`, { kind: "info" }))
      .catch((x: unknown) => toast(`The link wasn't sent: ${errText(x)}`, { kind: "err" }));
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
        {hasPassword ? (
          <div className="field">
            <label className="label" htmlFor="pw-cur">
              Current password
            </label>
            <input type="password" className={`input ${errs.cur ? "is-error" : ""}`} id="pw-cur" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />
            <Err k="cur" />
          </div>
        ) : (
          <div className="alert info">
            <Ic n="info" s={14} />
            <span>You don't have a password yet: set one to sign in with your email and a password too.</span>
          </div>
        )}
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
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {hasPassword ? "Update password" : "Set password"}
          </button>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start", marginLeft: -8 }} onClick={forgot}>
          Forgot it? Email me a link
        </button>
      </form>
    </>
  );
}

function TwoFA() {
  if (isLive())
    return (
      <div className="alert info">
        <Ic n="info" s={15} />
        <span>Two-factor authentication isn't available yet. Until it is, use a long password, or sign in with GitHub or an email link.</span>
      </div>
    );
  return <SeedTwoFA />;
}
function SeedTwoFA() {
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

/** Your notification settings in a real workspace: saved as you change them, in every workspace. */
function LiveNotifs({ sec }: { sec: string }) {
  const r = useApi(notifSettings);
  const [cur, setCur] = useState<NotifSettings | null>(null);
  if (r.error) return <div className="alert danger">{r.error}</div>;
  const v = cur ?? r.data;
  if (!v) return <div className="faint">Loading…</div>;
  const put = (patch: Partial<NotifSettings>) => {
    const next = { ...v, ...patch };
    setCur(next);
    notifSettingsSaved(next)
      .then((x) => setCur(x))
      .catch((e: unknown) => {
        setCur(v);
        toast(`Your notification settings didn't save: ${errText(e)}`, { kind: "err" });
      });
  };
  const T = (k: "mention" | "assigned" | "watching" | "finding" | "decided", label: string) => <Tog on={v[k]} set={(on) => put({ [k]: on })} label={label} />;
  const always = (what: string) => <Tog on set={() => toast(`${what} always come through`, { kind: "info" })} label={what} />;
  switch (sec) {
    case "notif-email":
      return (
        <>
          <SRow t="Email me" d="What you get in the app, by email too: as it happens (a run's changes together), a daily digest at 08:00 UTC of what's unread, or never.">
            <select className="select" style={{ width: "auto", minWidth: 180 }} value={v.email} onChange={(e) => put({ email: e.target.value as NotifSettings["email"] })} aria-label="Email me">
              <option value="immediately">As it happens</option>
              <option value="daily">Daily digest</option>
              <option value="off">Never</option>
            </select>
          </SRow>
          <p className="faint" style={{ fontSize: 12.5, marginTop: 12 }}>
            Which kinds reach you follows Mentions, Task assignments, and Agents. Emails go only to a verified address.
          </p>
        </>
      );
    case "notif-push":
      return (
        <div className="alert info">
          <Ic n="info" s={15} />
          <span>Push notifications aren't available yet: you get them in the app and by email.</span>
        </div>
      );
    case "notif-mentions":
      return (
        <SRow t="@mentions in comments and chat" d="When someone picks you after typing @.">
          {T("mention", "Mentions")}
        </SRow>
      );
    case "notif-assign":
      return (
        <>
          <SRow t="When I'm assigned a task" d="Not when you assign yourself.">
            {T("assigned", "Assignments")}
          </SRow>
          <SRow t="When I'm watching a task and it changes" d="Its changes and comments, not your own.">
            {T("watching", "Watching")}
          </SRow>
        </>
      );
    default:
      return (
        <>
          <SRow t="Changes waiting for approval" d="Always on: an agent's change never goes through without someone deciding.">
            {always("Approvals")}
          </SRow>
          <SRow t="Plans to steer" d="When an agent pauses before an expensive step.">
            {always("Checkpoints")}
          </SRow>
          <SRow t="Findings" d="When a review or research run finds something.">
            {T("finding", "Findings")}
          </SRow>
          <SRow t="Decisions on my requests" d="When someone else approves or rejects a change you asked for.">
            {T("decided", "Decisions")}
          </SRow>
        </>
      );
  }
}

/** Where you're signed in: browsers and the desktop app, then your tokens (the CLI's sign-ins, and any made for scripts). */
function LiveSessions() {
  const r = useApi(sessions);
  const cli = useApi(tokens);
  const [made, setMade] = useState<{ name: string; token: string } | null>(null);
  if (r.error) return <div className="alert danger">{r.error}</div>;
  if (!r.data) return <div className="faint">Loading…</div>;
  const out = (id: string) =>
    sessionSignedOut(id)
      .then(() => (r.reload(), toast("Signed out")))
      .catch((e: unknown) => toast(`It wasn't signed out: ${errText(e)}`, { kind: "err" }));
  const revoke = (id: string) =>
    tokenRevoked(id)
      .then(() => (cli.reload(), setMade(null), toast("Revoked")))
      .catch((e: unknown) => toast(`It wasn't revoked: ${errText(e)}`, { kind: "err" }));
  const create = () =>
    promptDlg({
      title: "New token",
      label: "What it's for (e.g. CI)",
      value: "",
      run: (v: string) => {
        const name = v.trim();
        if (!name) return;
        tokenCreated(name, 90)
          .then((t) => (setMade({ name: t.name, token: t.token }), cli.reload()))
          .catch((e: unknown) => toast(`The token wasn't created: ${errText(e)}`, { kind: "err" }));
      },
    });
  return (
    <>
      {r.data.map((x) => (
        <SRow
          key={x.id}
          t={
            <span className="row" style={{ gap: 8 }}>
              <Ic n={x.client === "desktop" ? "monitor" : /iPhone|Android/.test(x.device) ? "smartphone" : "globe"} s={15} />
              {x.device}
              {x.current && <span className="badge green">This browser</span>}
            </span>
          }
          d={`${x.ip ? `${x.ip} · ` : ""}last used ${ago(new Date(x.last_used_at).getTime())} · signed in ${fmtDate(x.created_at.slice(0, 10), true)}`}
        >
          {!x.current && (
            <button className="btn btn-secondary btn-sm" onClick={() => void out(x.id)}>
              Sign out
            </button>
          )}
        </SRow>
      ))}
      <div style={{ marginTop: 16 }}>
        <button
          className="btn btn-danger-ghost"
          disabled={r.data.length < 2}
          onClick={() =>
            otherSessionsSignedOut()
              .then(() => (r.reload(), toast("Signed out of every other browser and app")))
              .catch((e: unknown) => toast(`They weren't signed out: ${errText(e)}`, { kind: "err" }))
          }
        >
          Sign out of all other sessions
        </button>
      </div>
      <div className="sblock">
        <h2>Tokens</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Let something other than this browser act as you: the CLI gets one when you run{" "}
          <button className="btn btn-ghost btn-sm mono" style={{ padding: "0 4px", height: "auto" }} onClick={() => void copy("pmagent login", "Command copied")}>
            pmagent login
          </button>
          , and a script or CI job uses one in <span className="mono">PMAGENT_TOKEN</span>. A token can do what you can, and expires after 90 days.
        </p>
        {made && (
          <div className="alert ok" style={{ marginBottom: 12 }}>
            <Ic n="key-round" s={15} />
            <div className="grow" style={{ minWidth: 0 }}>
              <b>{made.name}</b>: copy it now, it isn't shown again.
              <div className="row" style={{ gap: 6, marginTop: 6 }}>
                <code className="mono grow trunc" style={{ fontSize: 12 }}>
                  {made.token}
                </code>
                <button className="btn btn-secondary btn-sm" onClick={() => void copy(made.token, "Token copied")}>
                  Copy
                </button>
              </div>
            </div>
          </div>
        )}
        {cli.error && <div className="alert danger">{cli.error}</div>}
        {(cli.data ?? []).map((t) => (
          <SRow
            key={t.id}
            t={
              <span className="row" style={{ gap: 8 }}>
                <Ic n={/cli|pmagent/i.test(t.name) ? "terminal" : "key-round"} s={15} />
                {t.name} <span className="faint mono">({t.display_prefix}…)</span>
              </span>
            }
            d={`${t.last_used_at ? `last used ${ago(new Date(t.last_used_at).getTime())}` : "never used"} · created ${fmtDate(t.created_at.slice(0, 10), true)}${t.expires_at ? ` · expires ${fmtDate(t.expires_at.slice(0, 10), true)}` : ""}`}
          >
            <button className="btn btn-secondary btn-sm" onClick={() => void revoke(t.id)}>
              Revoke
            </button>
          </SRow>
        ))}
        {cli.data && !cli.data.length && <p className="faint">No tokens. Nothing but your browsers is signed in as you.</p>}
        <div style={{ marginTop: 12 }}>
          <button className="btn btn-secondary btn-sm" onClick={create}>
            <Ic n="plus" s={13} />
            New token
          </button>
        </div>
      </div>
    </>
  );
}

/** What members can do, in a real workspace: the grants owners and admins set. */
function LivePermissions() {
  const ws = live.ws!;
  const admin = ws.role === "owner" || ws.role === "admin";
  const grants = ws.member_permissions ?? [];
  return (
    <>
      {ws.kind === "personal" ? (
        <div className="alert info" style={{ marginBottom: 14 }}>
          <Ic n="info" s={15} />
          <span>A personal workspace is just for you. Turn it into an organisation (Workspace) to invite people and decide what they can do.</span>
        </div>
      ) : null}
      <div className="sblock" style={{ marginTop: 0 }}>
        <h2>What members can do with the agents</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Off by default: a member's request that would change something waits for an owner or admin. Guests never get these.
        </p>
        {GRANTABLE.map(([perm, t, d]) => (
          <SRow key={perm} t={t} d={d}>
            <input
              type="checkbox"
              className="toggle"
              checked={grants.includes(perm)}
              disabled={!admin}
              onChange={(e) => void memberPermissionsSaved(e.target.checked ? [...grants, perm] : grants.filter((x) => x !== perm))}
              aria-label={t}
            />
          </SRow>
        ))}
      </div>
      <div className="sblock">
        <h2>Role permissions</h2>
        <div style={{ marginTop: 12 }}>
          <PermsTable />
        </div>
      </div>
    </>
  );
}

function Body({ sec }: { sec: string }) {
  const d = D();
  const Pr = S.prefs;
  if (isLive() && sec.startsWith("notif-")) return <LiveNotifs sec={sec} />;
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
                {m.role === "Owner" || m.id === d.me ? (
                  <span className="pillbtn">
                    {m.role === "Owner" && <Ic n="crown" s={13} />}
                    {m.role}
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
      if (isLive()) return <LivePermissions />;
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
      if (isLive()) return <LiveSessions />;
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
          <div className="sblock">
            <h2>Tokens</h2>
            <p className="muted" style={{ fontSize: 13 }}>
              Let something other than this browser act as you: the CLI after <span className="mono">pmagent login</span>, or a script or CI job.
            </p>
            {[
              ["terminal", "pmagent CLI on MacBook Pro", "last used 2 hours ago · expires Jan 3"],
              ["key-round", "CI (pmat_…7f3a)", "last used yesterday · expires Dec 11"],
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
  sessions: "Browsers and apps signed in to your account, and the tokens that act as you.",
  "2fa": "Add a second step when signing in.",
  plan: "Your subscription and usage.",
  payment: "Payment method and billing details.",
  invoices: "Past invoices for this workspace.",
};

export function Settings() {
  const { params } = useRoute();
  const asked = params.sec || S.ui.settings || "profile";
  const sec = asked === "devices" ? "sessions" : asked; // Devices and tokens is part of Sessions now
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
