import { Code as InlineCode } from "@dotrix/ui/astryx";
import { Textarea as DesignTextarea } from "@dotrix/ui/components/textarea";
import { SelectionInput } from "@dotrix/ui/components/selection-input";
import { Input as DesignInput } from "@dotrix/ui/components/input";
import { Switch, Selector, SegmentedControl, SegmentedControlItem } from "@dotrix/ui/astryx";
import { ActionButton } from "@dotrix/ui/components/action-button";
// Settings: a left nav of sections, each a set of rows.
// dotrix adds the agents' sections (owners and admins): Agents, Rules and skills, Automations,
// GitHub, What members can do, Audit log; and Devices and tokens (the CLI) under Security.
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { copy, openPop, setPref } from "../core/actions";
import { ACTION_OF } from "../core/agents";
import { allowed, canInvite, type Perm } from "../core/can";
import {
  desktopBrowser,
  desktopDevServers,
  setBrowserSettings,
  useBrowserSettings,
  useDesktopRunners,
  type BrowserSettings,
  type DevCommand,
} from "../core/desktop";
import { CODING_AGENT } from "../data/seed-dotrix";
import { organisations, personal, tasksLabel } from "../core/features";
import { Ic, WsLogo } from "../core/icons";
import { confirmDlg, invite, promptDlg, restoreProject } from "../core/more";
import { go, useRoute } from "../core/nav";
import { storageLine } from "../core/storage";
import { ago, dOff, fmtDate, uid } from "../core/utils";
import { ApiError } from "@/lib/api";
import { useBuiltinTeam } from "@/lib/team";

import {
  GRANTABLE,
  agentCatalog,
  apiHandle,
  agentDetail,
  agentReset,
  agentSaved,
  fieldsOf,
  githubRepos,
  githubStatus,
  installGitHub,
  installationRemoved,
  linkGitHub,
  memberPermissionsSaved,
  myAgentSaved,
  myAgents,
  myDefaultModelSaved,
  myCodingToolSaved,
  myCodeMode,
  myCodeModeSaved,
  myKeyRemoved,
  myKeySaved,
  myModels,
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
  unattendedPaused,
  approvalCap,
  skills,
  tokenCreated,
  tokenRevoked,
  tokens,
  sandboxNetwork,
  sandboxNetworkSaved,
  unlinkGitHub,
  useApi,
  workspaceRenamed,
  workspaceStorage,
  type AgentFields,
  type NotifSettings,
} from "../data/account";
import { automationAdded, automationRemoved, automationToggled, isLive, live, reloadAgents } from "../data/live";
import { D, S, me, mutate, proj, render, save, visibleProjects, who } from "../data/store";
import { useAgents, useAudit, useAutomations, useMembers, useProjects } from "../data/lists";
import { SHORTCUTS } from "../overlays/Modals";
import { Av, Empty, PIcon } from "../ui/helpers";
import { toast } from "../ui/toast";
import { PermsTable } from "./Members";
import { moodOf } from "../core/presence";
import { Face } from "../ui/face";

const css = (o: Record<string, string | number>) => o as CSSProperties;

const SET_NAV: [string, [string, string, string][], boolean?][] = [
  [
    "General",
    [
      ["workspace", "Workspace", "building-2"],
      ["datetime", "Date & time", "clock"],
    ],
  ],
  [
    "Workspace",
    [
      ["members", "Members", "users"],
      ["projects", "Projects", "folder-kanban"],
      ["permissions", "Permissions", "shield"],
    ],
  ],
  [
    "Agents",
    [
      ["agents", "Agents", "bot"],
      ["github", "GitHub", "github"],
      ["sandbox", "Network", "shield-check"],
      ["audit", "Audit log", "list-checks"],
    ],
    true,
  ],
  ["Notifications", [["notif-email", "Notifications", "bell"]]],
  [
    "Personal",
    [
      ["profile", "Profile", "user"],
      ["my-models", "Your models", "key-round"],
      ["my-agents", "Your agents", "bot"],
      ["browser", "Browser", "globe"],
      ["preferences", "Preferences", "sliders-horizontal"],
    ],
  ],
  [
    "Security",
    [
      ["password", "Password", "key-round"],
      ["sessions", "Sessions", "monitor-smartphone"],
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
function Tog({ on, set, label, disabled }: { on: boolean; set: (v: boolean) => void; label: string; disabled?: boolean }) {
  return <Switch value={on} onChange={set} label={label} isLabelHidden isDisabled={disabled} />;
}
const PTog = ({ k, def = true }: { k: string; def?: boolean }) => <Tog on={P()[k] === undefined ? def : Boolean(P()[k])} set={(v) => setP(k, v)} label={k} />;
const NTog = ({ k, def = false }: { k: string; def?: boolean }) => (
  <Tog on={NP()[k] === undefined ? def : Boolean(NP()[k])} set={(v) => setNP(k, v)} label={k} />
);
function Sel({ k, opts, v }: { k: string; opts: (string | [string, string])[]; v: unknown }) {
  return (
    <Selector
      label={k}
      isLabelHidden
      value={String(v)}
      onChange={(value) => setP(k, k === "weekStart" ? Number(value) : value)}
      options={opts.map((o) => {
        const [value, label] = Array.isArray(o) ? o : [o, o];
        return { value, label };
      })}
    />
  );
}
function Seg({ k, opts }: { k: "side" | "density"; opts: string[] }) {
  return (
    <SegmentedControl label={k} value={S.prefs[k]} onChange={(value) => setPref(k, value)}>
      {opts.map((value) => (
        <SegmentedControlItem key={value} value={value} label={value[0]!.toUpperCase() + value.slice(1)} />
      ))}
    </SegmentedControl>
  );
}

const ACCENTS: [string, string][] = [
  ["astryx", "#15110C"],
  ["indigo", "#4B5BD6"],
  ["blue", "#2F6CD4"],
  ["violet", "#7348CC"],
  ["teal", "#1A7F7A"],
  ["rose", "#B93D68"],
  ["graphite", "#34332F"],
];

function ThemeCards() {
  const L = { bg: "#F8F4ED", s: "#FFFFFF", t: "#15110C", b: "#DFE2E5", a: "#15110C" };
  const Dk = { bg: "#111112", s: "#202124", t: "#DFE2E5", b: "#383B3E", a: "#DFE2E5" };
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
        <button
          key={k}
          className={`tcard ${S.prefs.theme === k ? "on" : ""}`}
          role="radio"
          aria-checked={S.prefs.theme === k}
          onClick={() => setPref("theme", k)}
        >
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

/** Uploaded documents and task attachments against the workspace's limit; the seeded workspace shows a sample figure. */
function StorageUsage() {
  const live_ = isLive();
  const u = useApi(workspaceStorage);
  if (live_ && u.error) return <div className="hint">Storage usage didn't load.</div>;
  if (live_ && !u.data) return null;
  const line = live_ ? storageLine(u.data!.used_bytes, u.data!.limit_bytes) : storageLine(312_000_000, 1_000_000_000);
  return (
    <div className="sblock">
      <h2>Storage</h2>
      <div className="col" style={{ gap: 8, maxWidth: 440 }}>
        <div className="row" style={{ gap: 8 }}>
          <span className="grow">{line.text}</span>
          {!live_ && <span className="hint">Sample data</span>}
        </div>
        {line.ratio !== null && (
          <div
            className={`prog ${line.tone === "full" ? "red" : line.tone === "warn" ? "amber" : ""}`}
            style={css({ "--p": line.ratio, flex: "none", width: "100%" })}
            role="progressbar"
            aria-label="Storage used"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(line.ratio * 100)}
          >
            <i />
          </div>
        )}
        {line.note && (
          <span className="hint" style={{ color: "var(--red)" }}>
            {line.note}
          </span>
        )}
        <span className="hint">Counts uploaded documents and task attachments.</span>
      </div>
    </div>
  );
}

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
                  <button
                    key={c}
                    type="button"
                    className={`sw ${d.ws.c === c ? "on" : ""}`}
                    style={css({ "--c": c, width: 22, height: 22 })}
                    onClick={() => mutate(() => (d.ws.c = c))}
                    aria-label={`Color ${c}`}
                  />
                ))}
              </div>
            </div>
          </div>
          <div className="col" style={{ gap: 14, maxWidth: 440 }}>
            <div className="field">
              <label className="label" htmlFor="ws-name">
                Workspace name
              </label>
              <DesignInput aria-label="Workspace name" className="input" id="ws-name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="field">
              <label className="label" htmlFor="ws-url">
                Workspace URL
              </label>
              <div className="row" style={{ gap: 0 }}>
                <span
                  className="input"
                  style={{
                    width: "auto",
                    background: "var(--surface-2)",
                    borderRight: 0,
                    borderRadius: "6px 0 0 6px",
                    display: "flex",
                    alignItems: "center",
                    color: "var(--text-2)",
                  }}
                >
                  dotrix.app/w/
                </span>
                <DesignInput
                  aria-label="Workspace URL"
                  className="input"
                  id="ws-url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  style={{ borderRadius: "0 6px 6px 0" }}
                  disabled={isLive()}
                />
              </div>
              <span className="hint">{isLive() ? "The address is fixed when the workspace is created." : "Changing the URL will break existing links."}</span>
            </div>
            <div>
              <ActionButton className="btn btn-primary" type="submit">
                Save changes
              </ActionButton>
            </div>
          </div>
        </div>
      </form>
      <StorageUsage />
      {d.ws.kind === "personal" && organisations() && (
        <div className="sblock">
          <h2>Work with a team</h2>
          <SRow t="Create an organisation" d="Keep this workspace personal. Create a separate organisation, then move selected projects when needed.">
            {isLive() ? (
              <a className="btn btn-secondary" href="/onboarding?mode=project&team=1">
                Create organisation workspace
              </a>
            ) : (
              <ActionButton className="btn btn-secondary" onClick={() => toast("Sample workspace setup is read-only")}>
                Create organisation workspace
              </ActionButton>
            )}
          </SRow>
        </div>
      )}
      <div className="sblock">
        <h2 style={{ color: "var(--red)" }}>Danger zone</h2>
        <SRow t="Delete workspace" d="Permanently delete this workspace, its projects, tasks, documents, and files. This cannot be undone.">
          <ActionButton
            className="btn btn-danger-ghost"
            style={{ border: "1px solid color-mix(in srgb,var(--red) 35%,transparent)" }}
            onClick={() => toast("Deleting a workspace isn't available yet", { kind: "info" })}
          >
            Delete workspace
          </ActionButton>
        </SRow>
      </div>
    </>
  );
}

const errText = (e: unknown) => (e instanceof Error && e.message ? e.message : "try again");

/** An agent's contract in a real workspace: loaded from the API, saved as a new version. */
function LiveAgent({ handle }: { handle: string }) {
  const { items: agents } = useAgents();
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
  const look = agents.find((x) => x.handle === handle);
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
      title: `Reset ${ag.name} to its default?`,
      body: "Additional guidance and configuration return to the built-in defaults. Version history is kept.",
      ok: "Reset to default",
      icon: "rotate-ccw",
      run: () => {
        agentReset(handle)
          .then(async () => {
            toast("Reset to default");
            setF(null);
            await reloadAgents();
            a.reload();
          })
          .catch((e: unknown) => toast(`It didn't change: ${errText(e)}`, { kind: "err" }));
      },
    });
  const toggleTool = (id: string) => set({ tools: v.tools.includes(id) ? v.tools.filter((t) => t !== id) : [...v.tools, id] });
  return (
    <>
      <ActionButton className="btn btn-sm btn-ghost" onClick={back} style={{ margin: "-4px 0 12px -8px" }}>
        <Ic n="arrow-left" s={14} />
        All agents
      </ActionButton>
      <div className="row" style={{ gap: 12, marginBottom: 16 }}>
        <Face c={look?.c ?? "#57544E"} size={36} mood={moodOf(handle)} />
        <div className="grow" style={{ minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>
            {ag.name}{" "}
            <span className="faint mono" style={{ fontSize: 12, fontWeight: 400 }}>
              @{handle}
            </span>
          </h2>
          <div className="muted">{ag.description}</div>
        </div>
        <span className="badge">Built-in</span>
        {ag.source === "customised" && <span className="badge">Customised</span>}
        {ag.version != null && <span className="badge mono">v{ag.version}</span>}
      </div>
      <SRow t="Name">
        <DesignInput className="input" style={{ width: 220 }} value={v.name} readOnly aria-label="Name" />
      </SRow>
      <SRow t="Description" d="One line, shown in Chat's agent picker.">
        <DesignInput className="input" style={{ width: 320 }} value={v.description} readOnly aria-label="Description" />
      </SRow>
      {handle === "coding-agent" ? (
        <SRow t="Coding tool and model" d="Kai uses your coding preferences and credentials.">
          <ActionButton className="btn btn-secondary" onClick={() => go("settings", { sec: "my-models" })}>
            Your models
          </ActionButton>
        </SRow>
      ) : (
        <SRow t="Model" d="Which model this agent uses. Specialists use the project's specialist model when unset.">
          <select
            className="select"
            style={{ width: "auto", minWidth: 180 }}
            value={v.model ?? ""}
            onChange={(e) => set({ model: e.target.value || null })}
            aria-label="Model"
          >
            <option value="">Project or conversation default</option>
            {(ms.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
            {v.model && !(ms.data ?? []).some((m) => m.id === v.model) && <option value={v.model}>{v.model}</option>}
          </select>
        </SRow>
      )}
      {handle !== "coding-agent" && (
        <>
          <SRow t="Token budget" d="Tokens one run it leads may use; empty uses the project's.">
            <DesignInput
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
              From the catalogue. Writes wait for approval unless an owner allows them below.
            </p>
            {cat.data.tools
              .filter((tool) => ag.available_tools.includes(tool.id))
              .map((t) => (
                <SRow key={t.id} t={t.label} d={t.description}>
                  <Tog on={v.tools.includes(t.id)} set={() => toggleTool(t.id)} label={t.label} />
                </SRow>
              ))}
          </div>
          <div className="sblock">
            <h2>Without asking</h2>
            <p className="muted" style={{ fontSize: 13 }}>
              Only owners can let an agent act without asking; each change is recorded as approved by the owner who saved this version. Closing issues and
              coding always wait for a person, folder access still applies, and a run makes at most a few changes this way.
            </p>
            {live.ws?.unattended_paused && (
              <div className="alert warn" style={{ marginBottom: 8 }}>
                Paused for this workspace: every change waits for approval until an owner resumes it.
              </div>
            )}
            {cat.data.tools
              .filter((t) => t.actions.length && v.tools.includes(t.id))
              .flatMap((t) => t.actions.map((act) => [t, act] as const))
              .map(([t, act]) => {
                const rule = v.autonomy?.[act] ?? "ask";
                const risky = !cat.data!.low_risk_actions.includes(act);
                return (
                  <SRow key={act} t={t.label} d={rule === "allow" && risky ? "Changes go through without anyone approving them." : undefined}>
                    <select
                      className="select"
                      style={{ width: "auto" }}
                      value={rule}
                      onChange={(e) => set({ autonomy: { ...v.autonomy, [act]: e.target.value as "allow" | "ask" | "block" } })}
                      aria-label={`${t.label} without asking`}
                    >
                      <option value="ask">Ask first</option>
                      <option value="allow" disabled={!owner}>
                        Allow
                      </option>
                      <option value="block">Block</option>
                    </select>
                  </SRow>
                );
              })}
            {!owner && (
              <p className="faint" style={{ fontSize: 12.5 }}>
                Only owners can allow an action, or save a version that allows more than comments and links.
              </p>
            )}
          </div>
        </>
      )}
      <div className="sblock">
        <h2>Built-in instructions</h2>
        <DesignTextarea className="textarea" rows={6} value={ag.instructions} readOnly aria-label="Built-in instructions" />
        <h2>Additional instructions</h2>
        <DesignTextarea
          className="textarea"
          rows={10}
          value={v.additional_instructions ?? ""}
          onChange={(e) => set({ additional_instructions: e.target.value })}
          style={{ marginTop: 10 }}
          aria-label="Additional instructions"
        />
        <div className="row" style={{ marginTop: 10, gap: 6 }}>
          <ActionButton className="btn btn-primary" onClick={save} disabled={busy || !f}>
            Save
          </ActionButton>
          {f && (
            <ActionButton className="btn btn-ghost" onClick={() => setF(null)}>
              Discard
            </ActionButton>
          )}
          <span className="sp" />
          {ag.source === "customised" && (
            <ActionButton className="btn btn-secondary" onClick={reset}>
              Reset to default
            </ActionButton>
          )}
        </div>
      </div>
    </>
  );
}

function Agents() {
  const [guidance, setGuidance] = useState<Record<string, string>>({});
  const [kaiGuidance, setKaiGuidance] = useState("");
  const { items: agents } = useAgents();
  const roster = useBuiltinTeam(isLive() ? live.ws?.id : undefined);
  const sel = agents.find((a) => a.handle === S.ui.agentSel);
  if (isLive() && (sel || S.ui.agentSel === "coding-agent")) return <LiveAgent key={S.ui.agentSel} handle={S.ui.agentSel!} />;
  if (!isLive() && S.ui.agentSel === "coding-agent")
    return (
      <>
        <ActionButton className="btn btn-sm btn-ghost" onClick={() => ((S.ui.agentSel = null), render())}>
          <Ic n="arrow-left" s={14} />
          All agents
        </ActionButton>
        <h2>
          Kai <span className="badge">Built-in</span>
          {kaiGuidance && <span className="badge">Customised</span>}
        </h2>
        <p className="muted">Implements instructed work through Nova in Build mode.</p>
        <div className="sblock">
          <h2>Built-in instructions</h2>
          <DesignTextarea
            className="textarea"
            readOnly
            value="You are Kai, the built-in coding agent. Work only on the instructed change."
            aria-label="Built-in instructions"
          />
          <h2>Additional instructions</h2>
          <DesignTextarea
            className="textarea"
            value={guidance["coding-agent"] ?? kaiGuidance}
            onChange={(event) => setGuidance({ ...guidance, "coding-agent": event.target.value })}
            aria-label="Additional instructions"
          />
          <div className="row" style={{ marginTop: 10, gap: 6 }}>
            <ActionButton
              className="btn btn-primary"
              onClick={() => {
                setKaiGuidance(guidance["coding-agent"] ?? kaiGuidance);
                toast("Saved as a new version");
              }}
            >
              Save
            </ActionButton>
            {kaiGuidance && (
              <ActionButton
                className="btn btn-secondary"
                onClick={() => {
                  setKaiGuidance("");
                  setGuidance({ ...guidance, "coding-agent": "" });
                  toast("Reset to default");
                }}
              >
                Reset to default
              </ActionButton>
            )}
          </div>
        </div>
      </>
    );
  if (sel)
    return (
      <>
        <ActionButton className="btn btn-sm btn-ghost" onClick={() => ((S.ui.agentSel = null), render())} style={{ margin: "-4px 0 12px -8px" }}>
          <Ic n="arrow-left" s={14} />
          All agents
        </ActionButton>
        <div className="row" style={{ gap: 12, marginBottom: 16 }}>
          <Face c={sel.c} size={36} />
          <div>
            <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>
              {sel.name}{" "}
              <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>
                {sel.role}
              </span>{" "}
              <span className="faint mono" style={{ fontSize: 12, fontWeight: 400 }}>
                @{sel.handle}
              </span>
            </h2>
            <div className="muted">{sel.desc}</div>
          </div>
          <span className="sp" />
          <span className="badge">Built-in</span>
          {sel.customised && <span className="badge">Customised</span>}
        </div>
        <SRow t="Model" d="Which model this agent uses; the project's model when unset.">
          <select
            className="select"
            style={{ width: "auto", minWidth: 180 }}
            value={sel.model ?? ""}
            onChange={(e) => mutate(() => ((sel.model = e.target.value || undefined), (sel.customised = true)))}
          >
            <option value="">Project default</option>
            {["Gemini 3.8 Flash", "Claude Sonnet 5.5", "Claude Opus 5.5", "GPT-5.5"].map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </SRow>
        <SRow t="Tools" d="From the catalogue. Writes wait for approval unless an owner allows them.">
          <span className="row" style={{ gap: 4, flexWrap: "wrap", justifyContent: "flex-end" }}>
            {sel.tools.map((t) => (
              <span key={t} className="badge mono">
                {t}
              </span>
            ))}
          </span>
        </SRow>
        <div className="sblock">
          <h2>Without asking</h2>
          <p className="muted" style={{ fontSize: 13 }}>
            Changes an owner lets this agent make without waiting for approval. &ldquo;Always allow&rdquo; on a waiting change sets one here.
          </p>
          {Object.values(ACTION_OF).map(([act, what]) => (
            <SRow key={act} t={what[0]!.toUpperCase() + what.slice(1)}>
              <select
                className="select"
                style={{ width: "auto" }}
                value={sel.allows?.includes(act) ? "allow" : "ask"}
                onChange={(e) =>
                  mutate(
                    () => (
                      (sel.allows = e.target.value === "allow" ? [...(sel.allows ?? []), act] : (sel.allows ?? []).filter((x) => x !== act)),
                      (sel.customised = sel.builtIn || undefined)
                    ),
                  )
                }
                aria-label={`${what} without asking`}
              >
                <option value="ask">Ask first</option>
                <option value="allow">Allow</option>
              </select>
            </SRow>
          ))}
        </div>
        <div className="sblock">
          <h2>Built-in instructions</h2>
          <DesignTextarea
            className="textarea"
            rows={3}
            readOnly
            value={`You are ${sel.name}, the ${sel.role.toLowerCase()} agent. ${sel.desc}`}
            aria-label="Built-in instructions"
          />
          <h2>Additional instructions</h2>
          <DesignTextarea
            className="textarea"
            rows={6}
            value={guidance[sel.handle] ?? sel.additionalInstructions ?? ""}
            onChange={(event) => setGuidance({ ...guidance, [sel.handle]: event.target.value })}
            style={{ marginTop: 10 }}
            aria-label="Additional instructions"
          />
          <div className="row" style={{ marginTop: 10, gap: 6 }}>
            <ActionButton
              className="btn btn-primary"
              onClick={() => (
                mutate(() => {
                  sel.customised = true;
                  sel.additionalInstructions = guidance[sel.handle] ?? sel.additionalInstructions ?? "";
                }),
                toast("Saved as a new version")
              )}
            >
              Save
            </ActionButton>
            {sel.customised && (
              <ActionButton
                className="btn btn-secondary"
                onClick={() => {
                  mutate(() => {
                    sel.customised = false;
                    sel.model = undefined;
                    sel.additionalInstructions = "";
                  });
                  setGuidance({ ...guidance, [sel.handle]: "" });
                  toast("Reset to default");
                }}
              >
                Reset to default
              </ActionButton>
            )}
          </div>
        </div>
      </>
    );
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="muted" style={{ fontSize: 13 }}>
          {agents.length + 1} built-in agents · Nova leads the team
        </span>
      </div>
      <UnattendedPause />
      <div className="panel" style={{ overflow: "hidden" }}>
        {agents.map((a) => (
          <div key={a.handle} className="mini" style={{ minHeight: 52 }} onClick={() => ((S.ui.agentSel = a.handle), render())}>
            <Face c={a.c} size={26} mood={moodOf(a.handle)} />
            <div className="grow" style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 500 }}>
                {a.name}{" "}
                <span className="muted" style={{ fontSize: 12, fontWeight: 400 }}>
                  {a.role}
                </span>{" "}
                <span className="faint mono" style={{ fontSize: 11.5, fontWeight: 400 }}>
                  @{a.handle}
                </span>
              </div>
              <div className="faint trunc" style={{ fontSize: 12 }}>
                {a.desc}
              </div>
            </div>
            <span className="badge">Built-in</span>
            {a.customised && <span className="badge">Customised</span>}
            <Ic n="chevron-right" s={14} />
          </div>
        ))}
        <div
          className="mini"
          style={{ minHeight: 52 }}
          role="button"
          tabIndex={0}
          onClick={() => ((S.ui.agentSel = "coding-agent"), render())}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              S.ui.agentSel = "coding-agent";
              render();
            }
          }}
        >
          <Face c="var(--acc)" size={26} mood={moodOf("agent:coding-agent")} />
          <div className="grow">
            <b>Kai</b> <span className="muted">Coding</span>
            <div className="faint">Implements instructed work through Nova in Build mode.</div>
          </div>
          <span className="badge">Built-in</span>
          {(roster.data?.find((agent) => agent.handle === "coding-agent")?.customised || kaiGuidance) && <span className="badge">Customised</span>}
          <Ic n="chevron-right" s={14} />
        </div>
      </div>
    </>
  );
}

/** The workspace's switch for every agent's changes without approval: owners and admins pause, owners resume. */
function UnattendedPause() {
  const [demo, setDemo] = useState(false);
  const role = isLive() ? live.ws?.role : "owner";
  if (role !== "owner" && role !== "admin") return null;
  const paused = isLive() ? !!live.ws?.unattended_paused : demo;
  return (
    <div className="panel" style={{ padding: "4px 14px", marginBottom: 12 }}>
      <SRow
        t="Pause changes without approval"
        d={
          paused
            ? "Every agent asks before every change, whatever its contract allows."
            : "Agents make the changes their contracts allow without waiting. Pause to make every change ask."
        }
      >
        <Tog
          on={paused}
          set={(on) => (isLive() ? void unattendedPaused(on) : setDemo(on))}
          label="Pause changes without approval"
          disabled={paused && role !== "owner"}
        />
      </SRow>
      <ApprovalCap role={role} />
    </div>
  );
}

const CAPS: [string, string][] = [
  ["manual", "Manual: every change waits for a yes"],
  ["accept_edits", "Accept edits: what people ask for goes through, and coding starts at once"],
  ["auto", "Auto: the same, and checkpoints don't pause"],
];

/** The highest approval mode people may work in (only those who may approve agent changes go above Manual). */
function ApprovalCap({ role }: { role: string | undefined }) {
  const [demo, setDemo] = useState("manual");
  const cap = isLive() ? (live.ws?.approval_mode_cap ?? "manual") : demo;
  const paused = isLive() && !!live.ws?.unattended_paused;
  const at = CAPS.findIndex(([v]) => v === cap);
  return (
    <SRow
      t="Highest approval mode"
      d={
        paused
          ? "Paused: everyone works in Manual until changes without approval are resumed."
          : "How much people may let go through without waiting, in chat and coding. Only people who may approve agent changes go above Manual; closing issues, merging, and agent rules always need a person."
      }
    >
      <select
        className="input"
        value={cap}
        aria-label="Highest approval mode"
        disabled={paused}
        onChange={(e) => (isLive() ? void approvalCap(e.target.value as "manual" | "accept_edits" | "auto") : setDemo(e.target.value))}
      >
        {CAPS.map(([v, l], i) => (
          <option key={v} value={v} disabled={role !== "owner" && i > at}>
            {l}
          </option>
        ))}
      </select>
    </SRow>
  );
}

/* ---------- Your personal model keys ---------- */

interface KeyLook {
  provider: string;
  label: string;
  connected: boolean;
  last4?: string | null;
  updated_at?: string | null;
  limit_reached_at?: string | null;
  limit_message?: string | null;
}

/** A provider's key: connected or not, its limit if reached, and Connect / Replace / Remove. */
function KeyRow({ k, canEdit, onSave, onRemove }: { k: KeyLook; canEdit: boolean; onSave: (key: string) => Promise<unknown>; onRemove: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const state = k.connected
    ? `Connected · key ending ${k.last4}${k.updated_at ? ` · added ${ago(Date.parse(k.updated_at))}` : ""}`
    : "Not connected · add your own key to use this provider";
  const save = () => {
    if (!value.trim()) return;
    setBusy(true);
    onSave(value.trim())
      .then(() => (setEditing(false), setValue("")))
      .finally(() => setBusy(false));
  };
  return (
    <div className="srow-wrap">
      <SRow t={k.label} d={state}>
        {canEdit && !editing && (
          <span className="row" style={{ gap: 6 }}>
            {k.connected && (
              <ActionButton className="btn btn-sm btn-ghost" onClick={onRemove}>
                Remove
              </ActionButton>
            )}
            <ActionButton className="btn btn-sm btn-secondary" onClick={() => setEditing(true)}>
              {k.connected ? "Replace" : "Connect"}
            </ActionButton>
          </span>
        )}
      </SRow>
      {editing && (
        <div className="row" style={{ gap: 6, marginTop: 6 }}>
          <DesignInput
            className="input"
            type="password"
            autoComplete="off"
            placeholder={`${k.label} API key`}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            aria-label={`${k.label} API key`}
            autoFocus
            style={{ flex: 1 }}
          />
          <ActionButton className="btn btn-sm btn-ghost" onClick={() => (setEditing(false), setValue(""))}>
            Cancel
          </ActionButton>
          <ActionButton className="btn btn-sm btn-primary" onClick={save} disabled={busy || !value.trim()}>
            Save key
          </ActionButton>
        </div>
      )}
      {k.limit_reached_at && (
        <div className="alert warn" style={{ marginTop: 6 }}>
          <Ic n="triangle-alert" s={15} />
          <div>
            <b>Limit reached {ago(Date.parse(k.limit_reached_at))}.</b> {k.label} refused a run: {k.limit_message} Runs on its models stop until the limit
            resets; choose a smaller model in Your agents, or use a key with more room.
          </div>
        </div>
      )}
    </div>
  );
}

const DEMO_KEYS: KeyLook[] = [
  { provider: "anthropic", label: "Anthropic", connected: true, last4: "7Qa2", limit_reached_at: null, limit_message: null },
  { provider: "openai", label: "OpenAI", connected: false },
  {
    provider: "google_genai",
    label: "Google",
    connected: true,
    last4: "kP0e",
    limit_reached_at: new Date(Date.now() - 3_600_000 * 2).toISOString(),
    limit_message: "429 RESOURCE_EXHAUSTED: quota exceeded for requests per day.",
  },
];
const DEMO_MODELS = ["Claude Opus 5.5", "Claude Sonnet 5.5", "Claude Haiku 5.5", "Gemini 3.8 Flash"];

/* ---------- Personal: your own keys and model, your touches to the agents ---------- */

function CodeModeSettings() {
  const loaded = useApi(myCodeMode);
  const [sample, setSample] = useState(true);
  const [saving, setSaving] = useState(false);
  const data = isLive() ? loaded.data : { enabled: sample, available: true };
  if (loaded.error) return <div className="alert danger">{loaded.error}</div>;
  if (!data) return <div className="faint">Loading Code Mode…</div>;
  return (
    <SRow
      t="Code Mode"
      d={
        data.available
          ? "Let Nova combine reads and filter results in a script. Applies to new chat turns. Experimental; savings depend on the model and task."
          : "Code Mode is not enabled on this server."
      }
    >
      <Tog
        label="Code Mode"
        on={data.available && data.enabled}
        disabled={saving || !data.available}
        set={(enabled) => {
          if (!isLive()) {
            setSample(enabled);
            return;
          }
          setSaving(true);
          void myCodeModeSaved(enabled)
            .then(() => {
              toast("Code Mode preference saved");
              loaded.reload();
            })
            .catch((error: unknown) => toast(errText(error), { kind: "err" }))
            .finally(() => setSaving(false));
        }}
      />
    </SRow>
  );
}

function MyModels() {
  const demo = {
    keys: DEMO_KEYS.map((k) => ({ ...k, connected: false, last4: null, limit_reached_at: null })),
    default_model: null,
    default_coding_tool: "codex" as const,
    models: DEMO_MODELS,
  };
  const loaded = useApi<{
    keys: KeyLook[];
    default_model?: string | null;
    default_coding_tool?: "codex" | "claude-code" | "opencode" | "fx" | null;
    models: string[];
  }>(myModels);
  const data = isLive() ? loaded : { ...loaded, data: demo };
  if (data.error) return <div className="alert danger">{data.error}</div>;
  if (!data.data) return <div className="faint">Loading…</div>;
  const d = data.data;
  const save = (p: Promise<unknown>, ok: string) =>
    p.then(() => (toast(ok), data.reload())).catch((e: unknown) => toast(errText(e), { kind: "err", ms: 6000 }));
  return (
    <>
      <div className="sblock" style={{ marginTop: 0 }}>
        <h2>Your keys</h2>
        {!isLive() && <p className="hint">Sample settings · Sign in to connect your own model keys.</p>}
        <p className="muted" style={{ fontSize: 13 }}>
          Your own provider keys pay for your chat, coding, and scheduled runs in every workspace. Stored encrypted; only the last four characters are shown.
          Every person connects their own key.
        </p>
        {d.keys.map((k) => (
          <KeyRow
            key={k.provider}
            k={k}
            canEdit={isLive()}
            onSave={(v) =>
              isLive() ? save(myKeySaved(k.provider, v), `Your ${k.label} key is saved`) : Promise.resolve(toast(`Your ${k.label} key is saved`))
            }
            onRemove={() => (isLive() ? void save(myKeyRemoved(k.provider), `Your ${k.label} key is removed`) : toast(`Your ${k.label} key is removed`))}
          />
        ))}
      </div>
      <div className="sblock">
        <h2>Your default model</h2>
        <SRow
          t="New conversations and coding sessions"
          d="The model your new conversations and Kai's new coding sessions start on, when you have its provider key."
        >
          <select
            className="select"
            style={{ width: "auto", minWidth: 220 }}
            value={d.default_model ?? ""}
            onChange={(e) => (isLive() ? void save(myDefaultModelSaved(e.target.value || null), "Default model saved") : toast("Default model saved"))}
            aria-label="Your default model"
          >
            <option value="">Each project&apos;s model</option>
            {d.models.map((m) => (
              <option key={m} value={m}>
                {m.split(":")[1] ?? m}
              </option>
            ))}
          </select>
        </SRow>
      </div>
      <div className="sblock">
        <h2>Kai&apos;s coding engine</h2>
        <SRow
          t="Runs the model you pick"
          d="Kai codes on the model you pick for a session (your default model to start). Auto runs Anthropic models on Claude Code, OpenAI's on Codex, and the rest on OpenCode. A preferred engine is used wherever it can run the model. Existing sessions keep theirs."
        >
          <select
            className="select"
            aria-label="Kai's coding engine"
            value={d.default_coding_tool ?? ""}
            onChange={(e) => {
              const tool = e.target.value as "codex" | "claude-code" | "opencode" | "fx" | "";
              if (isLive()) void save(myCodingToolSaved(tool || null), "Coding engine saved");
              else toast("Coding engine saved");
            }}
          >
            <option value="">Auto · follows the model</option>
            <option value="codex">Codex · OpenAI</option>
            <option value="claude-code">Claude Code · Anthropic</option>
            <option value="opencode">OpenCode · any connected provider</option>
            <option value="fx">fx · OpenAI-compatible providers</option>
          </select>
        </SRow>
      </div>
    </>
  );
}

/** One agent's personal touches: instructions and a model, saved for you only. */
function MyAgentRow({
  a,
  pref,
  models,
  onSave,
}: {
  a: { handle: string; name: string; desc: string };
  pref?: { instructions: string; model?: string | null };
  models: string[];
  onSave: (instructions: string, model: string | null) => Promise<unknown>;
}) {
  const [text, setText] = useState(pref?.instructions ?? "");
  const [model, setModel] = useState(pref?.model ?? "");
  const [busy, setBusy] = useState(false);
  const changed = text !== (pref?.instructions ?? "") || model !== (pref?.model ?? "");
  return (
    <div className="sblock">
      <h2>
        {a.name}{" "}
        <span className="faint mono" style={{ fontSize: 12, fontWeight: 400 }}>
          @{a.handle}
        </span>
      </h2>
      <p className="muted" style={{ fontSize: 13 }}>
        {a.desc}
      </p>
      <DesignTextarea
        className="textarea"
        rows={3}
        maxLength={2000}
        placeholder="How you like it to work: tone, format, what to focus on"
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label={`How you like ${a.name} to work`}
      />
      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        {a.handle === "coding-agent" ? (
          <ActionButton className="btn btn-secondary btn-sm" onClick={() => go("settings", { sec: "my-models" })}>
            Coding tool and model
          </ActionButton>
        ) : (
          <select
            className="select"
            style={{ width: "auto", minWidth: 200 }}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            aria-label={`${a.name}'s model for you`}
          >
            <option value="">As the workspace set it</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {m.split(":")[1] ?? m}
              </option>
            ))}
          </select>
        )}
        <span className="faint" style={{ fontSize: 12 }}>
          {text.length}/2000
        </span>
        <span className="sp" />
        <ActionButton
          className="btn btn-primary btn-sm"
          disabled={!changed || busy}
          onClick={() => (setBusy(true), void onSave(text, model || null).finally(() => setBusy(false)))}
        >
          Save
        </ActionButton>
      </div>
    </div>
  );
}

function MyAgents() {
  const agents = [...useAgents().items, { handle: "coding-agent", name: "Kai", desc: "Implements your instructed coding work." }];
  const prefs = useApi(isLive() ? myAgents : async () => [] as { handle: string; instructions: string; model?: string | null }[]);
  const ms = useApi(isLive() ? models : async () => DEMO_MODELS.map((m) => ({ id: m })));
  if (prefs.error) return <div className="alert danger">{prefs.error}</div>;
  if (!prefs.data || !ms.data) return <div className="faint">Loading…</div>;
  return (
    <>
      <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
        Within limits: your touches can&apos;t change what an agent may do, read, or change, and automations don&apos;t use them. A model of your own needs your
        key for it.
      </p>
      {agents.map((a) => (
        <MyAgentRow
          key={a.handle}
          a={a}
          pref={prefs.data!.find((p) => p.handle === apiHandle(a.handle))}
          models={ms.data!.map((m) => m.id)}
          onSave={(text, model) =>
            isLive()
              ? myAgentSaved(a.handle, text, model)
                  .then(() => (toast(`${a.name} saved for you`), prefs.reload()))
                  .catch((e: unknown) => toast(`${a.name} didn't save: ${errText(e)}`, { kind: "err", ms: 6000 }))
              : Promise.resolve(toast(`${a.name} saved for you`))
          }
        />
      ))}
    </>
  );
}

/** One workspace rule or skill: edited in place, saved as a new version over the one it was based on. */
function VersionedText({
  title,
  content,
  version,
  save,
  rows = 7,
}: {
  title: string;
  content: string;
  version: number;
  save: (text: string, base: number) => Promise<{ version: number }>;
  rows?: number;
}) {
  const [text, setText] = useState(content);
  const [ver, setVer] = useState(version);
  const [busy, setBusy] = useState(false);
  const changed = text !== content;
  return (
    <>
      <DesignTextarea
        className="textarea mono"
        rows={rows}
        value={text}
        onChange={(e) => setText(e.target.value)}
        style={{ fontSize: 12.5 }}
        aria-label={title}
      />
      <div className="row" style={{ marginTop: 10, gap: 6 }}>
        <ActionButton
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
        </ActionButton>
        {ver > 0 && (
          <span className="faint mono" style={{ fontSize: 12 }}>
            v{ver}
          </span>
        )}
      </div>
    </>
  );
}

function LiveRules() {
  const r = useApi(rules);
  const sk = useApi(skills);
  if (r.error || sk.error) return <div className="alert danger">{r.error || sk.error}</div>;
  if (!r.data || !sk.data) return <div className="faint">Loading…</div>;
  return (
    <RulesEditor
      base={r.data.find((item) => item.handle === "base")}
      items={sk.data}
      saveRule={(text, version) => ruleSaved("base", text, version).then((saved) => (r.reload(), saved))}
      saveSkill={(name, text, version) => skillSaved(name, text, version).then((saved) => (sk.reload(), saved))}
    />
  );
}

function RulesEditor({
  base,
  items,
  saveRule,
  saveSkill,
}: {
  base: { content: string; version: number } | undefined;
  items: { name: string; description: string; content: string; version: number }[];
  saveRule: (text: string, version: number) => Promise<{ version: number }>;
  saveSkill: (name: string, text: string, version: number) => Promise<{ version: number }>;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <div className="sblock" style={{ marginTop: 0 }}>
        <h2>Rules for every project</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Layered under each project's own <span className="mono">agent-rules/</span>, so a project's rules win.
        </p>
        <VersionedText title="Rules" content={base?.content ?? ""} version={base?.version ?? 0} save={(t, b) => saveRule(t, b)} />
      </div>
      <div className="sblock">
        <h2>Skills</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Procedures every project's agents can read when the work calls for one. A project's own skill of the same name wins.
        </p>
        {items.map((x) => (
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
              <ActionButton className="btn btn-secondary btn-sm" onClick={() => setOpen(open === x.name ? null : x.name)}>
                {open === x.name ? "Close" : "Edit"}
              </ActionButton>
            </SRow>
            {open === x.name && (
              <div style={{ padding: "4px 0 14px" }}>
                <VersionedText title={x.name} content={x.content} version={x.version} rows={12} save={(t, b) => saveSkill(x.name, t, b)} />
              </div>
            )}
          </div>
        ))}
        {!items.length && <p className="faint">No workspace skills yet. Each project starts with its own in agent-rules/skills/.</p>}
        <div style={{ marginTop: 12 }}>
          <ActionButton
            className="btn btn-secondary btn-sm"
            onClick={() =>
              promptDlg({
                title: "New skill",
                label: "Name (lowercase, with dashes)",
                value: "",
                run: (v: string) => {
                  const name = v
                    .trim()
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, "-")
                    .replace(/^-+|-+$/g, "");
                  if (!name) return;
                  saveSkill(name, `Description: what this skill is for.\n\n1. The first step.\n2. The next.`, 0)
                    .then(() => (setOpen(name), toast(`Added ${name}: describe its steps`)))
                    .catch((e: unknown) => toast(`The skill wasn't added: ${errText(e)}`, { kind: "err" }));
                },
              })
            }
          >
            <Ic n="plus" s={13} />
            New skill
          </ActionButton>
        </div>
      </div>
    </>
  );
}

const Rules = () => (isLive() ? <LiveRules /> : <SeedRules />);
function SeedRules() {
  const [base, setBase] = useState({
    content: "- Write in plain English.\n- Link issues by key (WEB-12).\n- Never promise dates the board doesn't support.",
    version: 1,
  });
  const [items, setItems] = useState([
    {
      name: "write-an-adr",
      description: "Write an architecture decision record",
      content: "Description: Write an architecture decision record.\n\n1. Describe the decision and alternatives.\n2. Link the supporting evidence.",
      version: 1,
    },
    ...[
      ["triage-a-bug", "Triage a bug", "Reproduce the issue, identify its impact, and link evidence."],
      ["break-down-a-feature", "Break down a feature", "Define acceptance criteria and split the work into ordered tasks."],
      ["scope-a-failing-build", "Scope a failing build", "Read the failing check, identify affected files, and propose a focused fix."],
    ].map(([name, description, steps]) => ({ name: name!, description: description!, content: `Description: ${description}.\n\n${steps}`, version: 1 })),
  ]);
  return (
    <>
      <p className="muted">Sample settings. Changes last until you leave this page.</p>
      <RulesEditor
        base={base}
        items={items}
        saveRule={async (text, version) => {
          const saved = { content: text, version: version + 1 };
          setBase(saved);
          return saved;
        }}
        saveSkill={async (name, text, version) => {
          const saved = { name, description: text.split("\n")[0]!.replace(/^Description:\s*/, ""), content: text, version: version + 1 };
          setItems((current) => [...current.filter((item) => item.name !== name), saved]);
          return saved;
        }}
      />
    </>
  );
}

function Automations() {
  const { items: automations } = useAutomations();
  return (
    <>
      <div className="panel" style={{ overflow: "hidden" }}>
        {automations.length ? (
          automations.map((a) => {
            const p = proj(a.project);
            return (
              <div key={a.id} className="mini" style={{ minHeight: 56, cursor: "default", gap: 12 }}>
                <span className="ftype" style={css({ "--c": "var(--acc)" })}>
                  <Ic n="zap" s={14} />
                </span>
                <div className="grow" style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 500 }}>{a.name}</div>
                  <div className="faint trunc" style={{ fontSize: 12 }}>
                    {who(a.agent)?.name ?? a.agent} · {a.trigger} · {p?.name}
                    {a.last ? ` · last ran ${ago(a.last)}` : ""}
                  </div>
                  {a.lastError && (
                    <div className="muted" style={{ fontSize: 12 }}>
                      {a.lastError}
                    </div>
                  )}
                </div>
                <label
                  className="row faint"
                  style={{ gap: 6, fontSize: 12.5, whiteSpace: "nowrap" }}
                  title="Its runs may make the changes the agent's contract allows without approval; off: they ask"
                >
                  <SelectionInput
                    aria-label="Without approval"
                    type="checkbox"
                    checked={!!a.unattended}
                    disabled={isLive() && live.ws?.role !== "owner" && !a.unattended}
                    onChange={(e) => {
                      const on = e.target.checked;
                      if (isLive()) automationToggled({ ...a, unattended: on }, "unattended");
                      else mutate(() => (a.unattended = on));
                    }}
                  />
                  Without approval
                </label>
                <Tog
                  on={a.enabled}
                  set={(v) => {
                    if (isLive()) automationToggled({ ...a, enabled: v });
                    else mutate(() => (a.enabled = v));
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
          ["Triage new bugs", "When an issue is created, Nova checks for duplicates and fills in the fields."],
        ].map(([n, d]) => {
          const on = automations.some((x) => x.name === n);
          return (
            <SRow key={n} t={n} d={d}>
              <Tog
                on={on}
                label={`Turn ${n} on`}
                set={(v) => {
                  if (v) {
                    if (isLive()) {
                      void automationAdded(visibleProjects()[0]!.id, n!);
                      return;
                    }
                    mutate(() =>
                      D().automations.push({
                        id: uid("am"),
                        project: visibleProjects()[0]!.id,
                        name: n!,
                        agent: n!.startsWith("Triage") ? "auto" : "documentation",
                        trigger: n!.startsWith("Triage") ? "When an issue is created" : "Weekly, Monday 08:00",
                        enabled: true,
                      }),
                    );
                    toast(`Added “${n}”`);
                    return;
                  }
                  const existing = D().automations.filter((x) => x.name === n);
                  if (isLive()) existing.forEach((x) => automationRemoved(x));
                  mutate(() => (D().automations = D().automations.filter((x) => x.name !== n)));
                  toast(`Removed “${n}”`);
                }}
              />
            </SRow>
          );
        })}
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
  const connect = (pid: string, key: string, id: string) => {
    const r = id ? ((repos.data ?? []).find((x) => `${x.installation_ref}:${x.github_repo_id}` === id) ?? null) : null;
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
  return (
    <GitHubContent
      status={st.data}
      options={repos.data}
      admin={admin}
      busy={busy}
      onConnect={connect}
      onRemove={(id, login) => {
        void installationRemoved(id)
          .then(() => (st.reload(), repos.reload(), toast(`Removed ${login}`)))
          .catch((error: unknown) => toast(`It wasn't removed: ${errText(error)}`, { kind: "err" }));
      }}
      onInstall={() => installGitHub(st.data!)}
    />
  );
}

type GitHubViewStatus = {
  configured: boolean;
  install_url: string | null;
  installations: { id: string; account_login: string; account_type: string; suspended: boolean; created_at: string }[];
};
function GitHubContent({
  status: s,
  options,
  admin,
  busy,
  onConnect,
  onRemove,
  onInstall,
}: {
  status: GitHubViewStatus;
  options: Awaited<ReturnType<typeof githubRepos>> | undefined;
  admin: boolean;
  busy: string;
  onConnect: (projectId: string, key: string, repo: string) => void;
  onRemove: (id: string, login: string) => void;
  onInstall: () => void;
}) {
  const { items: projects } = useProjects();
  const byProject = new Map((options ?? []).filter((repo) => repo.project_key).map((repo) => [repo.project_key!, repo]));
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
              <ActionButton
                className="btn btn-secondary btn-sm"
                onClick={() =>
                  confirmDlg({
                    title: `Remove ${i.account_login}?`,
                    body: "Projects with a repository from this account lose it. The app stays installed on GitHub until you uninstall it there.",
                    ok: "Remove",
                    danger: true,
                    icon: "github",
                    run: () => {
                      onRemove(i.id, i.account_login);
                    },
                  })
                }
              >
                Remove
              </ActionButton>
            )}
          </SRow>
        ))}
        {!s.installations.length && (
          <p className="faint">No GitHub accounts yet. Install the app on an account to connect its repositories, private ones too.</p>
        )}
        {admin && s.install_url && (
          <div style={{ marginTop: 12 }}>
            <ActionButton className="btn btn-secondary" onClick={onInstall}>
              <Ic n="plus" s={14} />
              Add a GitHub account
            </ActionButton>
          </div>
        )}
      </div>
      <div className="sblock">
        <h2>Connected repositories</h2>
        {projects.map((p) => {
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
                disabled={!admin || busy === p.key || !options}
                onChange={(e) => onConnect(p.id, p.key, e.target.value)}
                aria-label={`Repository for ${p.name}`}
              >
                <option value="">No repository</option>
                {(options ?? [])
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

// The seeded workspace's presets (a real one reads them from the API, with what it allows).
const DEMO_PRESETS: Record<string, { label: string; hosts: string[] }> = {
  npm: { label: "npm (and pnpm, Yarn)", hosts: ["registry.npmjs.org", "registry.yarnpkg.com"] },
  pypi: { label: "PyPI (pip, uv)", hosts: ["pypi.org", "files.pythonhosted.org"] },
  go: { label: "Go modules", hosts: ["proxy.golang.org", "sum.golang.org"] },
};

/** Owners and admins choose the hosts Kai's sandboxes may reach besides the model API: for every project,
 *  and on top of that for one. Each is somewhere an agent could send data, so it stays a short list. */
function SandboxNetworkSettings() {
  const { items: projects } = useProjects();
  const [scope, setScope] = useState("");
  const loaded = useApi(() => sandboxNetwork(scope || undefined), [scope]);
  const [presets, setPresets] = useState<string[] | null>(null);
  const [hosts, setHosts] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const data = isLive() ? loaded.data : { presets: [], hosts: [], effective: [], available_presets: DEMO_PRESETS };
  if (isLive() && loaded.error) return <div className="alert danger">{loaded.error}</div>;
  if (!data) return <div className="faint">Loading…</div>;
  const available = data.available_presets as Record<string, { label: string; hosts: string[] }>;
  const chosen = presets ?? data.presets;
  const typed = hosts ?? data.hosts.join("\n");
  const changed = presets !== null || hosts !== null;
  const pick = (scopeId: string) => {
    setScope(scopeId);
    setPresets(null);
    setHosts(null);
  };
  const save = () => {
    const body = { presets: chosen, hosts: typed.split(/[\s,]+/).filter(Boolean) };
    if (!isLive()) {
      toast("Saved");
      return;
    }
    setBusy(true);
    sandboxNetworkSaved(body, scope || undefined)
      .then(() => {
        setPresets(null);
        setHosts(null);
        loaded.reload();
        toast("Network saved");
      })
      .catch((e: unknown) => toast(`It didn't save: ${errText(e)}`, { kind: "err", ms: 6000 }))
      .finally(() => setBusy(false));
  };
  return (
    <>
      <div className="alert info" style={{ marginBottom: 16 }}>
        <Ic n="shield-check" s={15} />
        <span>
          Kai's sandboxes reach only the model API. Each host you allow is somewhere an agent could also send your code, so allow only what turns need, such as
          a package registry. They apply to Docker Cloud sandboxes, which keep the model key out of the sandbox; other sandboxes refuse a turn while any are
          allowed.
        </span>
      </div>
      <div className="sblock" style={{ marginTop: 0 }}>
        <SRow t="Applies to" d={scope ? "This project, on top of what every project may reach" : "Every project"}>
          <select className="select" style={{ width: "auto", minWidth: 200 }} value={scope} onChange={(e) => pick(e.target.value)} aria-label="Applies to">
            <option value="">Every project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </SRow>
      </div>
      <div className="sblock">
        <h2>Package registries</h2>
        {Object.entries(available).map(([key, preset]) => (
          <SRow key={key} t={preset.label} d={<span className="mono">{preset.hosts.join(", ")}</span>}>
            <Tog on={chosen.includes(key)} set={(on) => setPresets(on ? [...chosen, key] : chosen.filter((k) => k !== key))} label={preset.label} />
          </SRow>
        ))}
      </div>
      <div className="sblock">
        <h2>Other hosts</h2>
        <p className="faint" style={{ marginTop: 0 }}>
          One per line: an exact name such as <span className="mono">api.example.com</span>, or <span className="mono">*.example.com</span> for that domain's
          hosts. HTTPS only.
        </p>
        <DesignTextarea
          className="textarea mono"
          rows={5}
          value={typed}
          onChange={(e) => setHosts(e.target.value)}
          placeholder="api.example.com"
          aria-label="Other hosts"
          style={{ maxWidth: 520 }}
        />
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <ActionButton className="btn btn-primary btn-sm" disabled={!changed || busy} onClick={save}>
            Save
          </ActionButton>
          {changed && (
            <ActionButton className="btn btn-secondary btn-sm" disabled={busy} onClick={() => (setPresets(null), setHosts(null))}>
              Discard
            </ActionButton>
          )}
        </div>
      </div>
      {isLive() && (
        <div className="sblock">
          <h2>{scope ? "This project's sandboxes may reach" : "Every project's sandboxes may reach"}</h2>
          {data.effective.length ? (
            <div className="mono" style={{ fontSize: 12.5, display: "flex", flexDirection: "column", gap: 2 }}>
              {data.effective.map((h) => (
                <span key={h}>{h}</span>
              ))}
            </div>
          ) : (
            <p className="faint">Only the model API.</p>
          )}
        </div>
      )}
    </>
  );
}

function GitHub() {
  if (isLive()) return <LiveGitHub />;
  const options = visibleProjects().flatMap((project, index) =>
    project.repo
      ? [
          {
            installation_ref: "sample-github",
            github_repo_id: index + 1,
            full_name: project.repo.replace(/^https:\/\/github.com\//, ""),
            private: false,
            default_branch: "main",
            html_url: project.repo.startsWith("https://") ? project.repo : `https://github.com/${project.repo}`,
            project_key: project.key,
          },
        ]
      : [],
  );
  const sampleAction = () => toast("Sign in to connect your GitHub account. Sample connections are read-only.", { kind: "info" });
  return (
    <>
      <p className="muted">Sample GitHub connections. Your live workspace uses your own installations and repository permissions.</p>
      <GitHubContent
        status={{
          configured: true,
          install_url: "sample",
          installations: [{ id: "sample-github", account_login: "dotrix", account_type: "Organization", suspended: false, created_at: "2026-01-01T00:00:00Z" }],
        }}
        options={options}
        admin
        busy=""
        onConnect={sampleAction}
        onRemove={sampleAction}
        onInstall={sampleAction}
      />
    </>
  );
}

function Audit() {
  const { items: audit } = useAudit();
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
          {audit.map((a) => (
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
              <button
                key={c}
                type="button"
                className={`sw ${me()!.c === c ? "on" : ""}`}
                style={css({ "--c": c, width: 22, height: 22 })}
                onClick={() => mutate(() => (me()!.c = c))}
                aria-label="Color"
              />
            ))}
          </div>
        </div>
      </div>
      <div className="field">
        <label className="label" htmlFor="pf-name">
          Full name
        </label>
        <DesignInput aria-label="Full name" className={`input ${err ? "is-error" : ""}`} id="pf-name" value={name} onChange={(e) => setName(e.target.value)} />
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
        <DesignInput aria-label="What you do" className="input" id="pf-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="field">
        <label className="label" htmlFor="pf-email">
          Email
        </label>
        <DesignInput aria-label="Email" className="input" id="pf-email" value={me()!.email} disabled />
        <span className="hint">Verified. Contact a workspace owner to change your sign-in email.</span>
      </div>
      <div className="sblock" style={{ marginTop: 4 }}>
        <h2>Sign-in methods</h2>
        <SRow t="Password" d={!isLive() || methods.data?.password ? "Set" : "Not set: you sign in with an email link or GitHub"}>
          <ActionButton type="button" className="btn btn-secondary btn-sm" onClick={() => go("settings", { sec: "password" })}>
            {!isLive() || methods.data?.password ? "Change" : "Set one"}
          </ActionButton>
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
            <ActionButton
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() =>
                unlinkGitHub()
                  .then(() => (methods.reload(), toast("GitHub unlinked")))
                  .catch((er: unknown) => toast(`GitHub stays linked: ${errText(er)}`, { kind: "err", ms: 6000 }))
              }
            >
              Unlink
            </ActionButton>
          ) : (
            <ActionButton
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => (isLive() ? linkGitHub() : toast("Linking opens GitHub", { kind: "info" }))}
            >
              Link
            </ActionButton>
          )}
        </SRow>
      </div>
      <div>
        <ActionButton className="btn btn-primary" type="submit">
          Save profile
        </ActionButton>
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
            <DesignInput
              aria-label="Current password"
              type="password"
              className={`input ${errs.cur ? "is-error" : ""}`}
              id="pw-cur"
              autoComplete="current-password"
              value={cur}
              onChange={(e) => setCur(e.target.value)}
            />
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
          <DesignInput
            aria-label="New password"
            type="password"
            className={`input ${errs.pw ? "is-error" : ""}`}
            id="pw-new"
            autoComplete="new-password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
          />
          <StrengthMeter pw={pw} />
          {errs.pw ? <Err k="pw" /> : <span className="hint">At least 10 characters with a number or symbol.</span>}
        </div>
        <div className="field">
          <label className="label" htmlFor="pw-conf">
            Confirm new password
          </label>
          <DesignInput
            aria-label="Confirm new password"
            type="password"
            className={`input ${errs.conf ? "is-error" : ""}`}
            id="pw-conf"
            autoComplete="new-password"
            value={conf}
            onChange={(e) => setConf(e.target.value)}
          />
          <Err k="conf" />
        </div>
        <div>
          <ActionButton className="btn btn-primary" type="submit" disabled={busy}>
            {hasPassword ? "Update password" : "Set password"}
          </ActionButton>
        </div>
        <ActionButton type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: "flex-start", marginLeft: -8 }} onClick={forgot}>
          Forgot it? Email me a link
        </ActionButton>
      </form>
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
  const T = (k: "mention" | "assigned" | "watching" | "finding" | "decided" | "stale" | "coding", label: string) => (
    <Tog on={v[k]} set={(on) => put({ [k]: on })} label={label} />
  );
  const always = (what: string) => <Tog on set={() => toast(`${what} always come through`, { kind: "info" })} label={what} />;
  switch (sec) {
    case "notif-email":
      return (
        <>
          <SRow
            t="Email me"
            d="What you get in the app, by email too: as it happens (a run's changes together), a daily digest at 08:00 UTC of what's unread, or never."
          >
            <select
              className="select"
              style={{ width: "auto", minWidth: 180 }}
              value={v.email}
              onChange={(e) => put({ email: e.target.value as NotifSettings["email"] })}
              aria-label="Email me"
            >
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
          <SRow t="Kai's turns" d="When a coding turn you asked for opens or updates its pull request, finishes without changes, or fails.">
            {T("coding", "Coding turns")}
          </SRow>
          <SRow t="Wiki pages out of date" d="When a push changes code that the project's wiki pages cite (if you edit documents).">
            {T("stale", "Out-of-date pages")}
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
            <ActionButton className="btn btn-secondary btn-sm" onClick={() => void out(x.id)}>
              Sign out
            </ActionButton>
          )}
        </SRow>
      ))}
      <div style={{ marginTop: 16 }}>
        <ActionButton
          className="btn btn-danger-ghost"
          disabled={r.data.length < 2}
          onClick={() =>
            otherSessionsSignedOut()
              .then(() => (r.reload(), toast("Signed out of every other browser and app")))
              .catch((e: unknown) => toast(`They weren't signed out: ${errText(e)}`, { kind: "err" }))
          }
        >
          Sign out of all other sessions
        </ActionButton>
      </div>
      <div className="sblock">
        <h2>Tokens</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Let something other than this browser act as you: the CLI gets one when you run{" "}
          <ActionButton
            className="btn btn-ghost btn-sm mono"
            style={{ padding: "0 4px", height: "auto" }}
            onClick={() => void copy("dotrix login", "Command copied")}
          >
            dotrix login
          </ActionButton>
          , and a script or CI job uses one in <span className="mono">DOTRIX_TOKEN</span>. A token can do what you can, and expires after 90 days.
        </p>
        {made && (
          <div className="alert ok" style={{ marginBottom: 12 }}>
            <Ic n="key-round" s={15} />
            <div className="grow" style={{ minWidth: 0 }}>
              <b>{made.name}</b>: copy it now, it isn't shown again.
              <div className="row" style={{ gap: 6, marginTop: 6 }}>
                <InlineCode className="mono grow trunc" style={{ fontSize: 12 }}>
                  {made.token}
                </InlineCode>
                <ActionButton className="btn btn-secondary btn-sm" onClick={() => void copy(made.token, "Token copied")}>
                  Copy
                </ActionButton>
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
                <Ic n={/cli|dotrix/i.test(t.name) ? "terminal" : "key-round"} s={15} />
                {t.name} <span className="faint mono">({t.display_prefix}…)</span>
              </span>
            }
            d={`${t.last_used_at ? `last used ${ago(new Date(t.last_used_at).getTime())}` : "never used"} · created ${fmtDate(t.created_at.slice(0, 10), true)}${t.expires_at ? ` · expires ${fmtDate(t.expires_at.slice(0, 10), true)}` : ""}`}
          >
            <ActionButton className="btn btn-secondary btn-sm" onClick={() => void revoke(t.id)}>
              Revoke
            </ActionButton>
          </SRow>
        ))}
        {cli.data && !cli.data.length && <p className="faint">No tokens. Nothing but your browsers is signed in as you.</p>}
        <div style={{ marginTop: 12 }}>
          <ActionButton className="btn btn-secondary btn-sm" onClick={create}>
            <Ic n="plus" s={13} />
            New token
          </ActionButton>
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
          <span>A personal workspace is just for you. Create a separate organisation workspace to invite people and decide what they can do.</span>
        </div>
      ) : null}
      <div className="sblock" style={{ marginTop: 0 }}>
        <h2>What members can do with the agents</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          Off by default: a member's request that would change something waits for an owner or admin. Guests never get these.
        </p>
        {GRANTABLE.map(([perm, t, d]) => (
          <SRow key={perm} t={t} d={d}>
            <SelectionInput
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

/** The desktop app's Browser pane: on or off, Kai's use of it, and what its pages keep. Saved by the app, for this computer. */
function BrowserSettingsPage() {
  const bridge = desktopBrowser();
  const settings = useBrowserSettings();
  if (!bridge) return <p className="muted">The Browser pane is part of the dotrix desktop app. Open Settings there to change it.</p>;
  const change = (send: () => Promise<BrowserSettings>) => () =>
    void send()
      .then(setBrowserSettings)
      .catch(() => toast("The setting couldn't be saved"));
  const on = settings?.enabled ?? false;
  return (
    <>
      <SRow t="Browser pane" d="Open your running app or any web page beside a coding session, in a profile apart from dotrix and your everyday browser.">
        <Tog on={on} set={(v) => change(() => bridge.setEnabled(v))()} label="Browser pane" disabled={!settings} />
      </SRow>
      <SRow
        t={`Let ${CODING_AGENT.name} use the browser`}
        d={`On a turn coding on this computer, ${CODING_AGENT.name} can open your running app in a tab of its own to check its change. Its tab opens only pages on this computer.`}
      >
        <Tog
          on={on && (settings?.kaiAllowed ?? false)}
          set={(v) => change(() => bridge.setKaiAllowed(v))()}
          label={`Let ${CODING_AGENT.name} use the browser`}
          disabled={!on}
        />
      </SRow>
      <SRow t="Keep cookies after quitting" d="Off, pages in the pane are signed out each time you quit dotrix.">
        <Tog
          on={on && (settings?.keepCookies ?? false)}
          set={(v) => change(() => bridge.setKeepCookies(v))()}
          label="Keep cookies after quitting"
          disabled={!on}
        />
      </SRow>
      <SRow t="Browsing data" d="Cookies, storage and cache saved by pages in the pane.">
        <ActionButton
          className="btn btn-sm"
          onClick={() =>
            void bridge.clear().then(
              () => toast("Browsing data cleared"),
              () => toast("The browsing data couldn't be cleared"),
            )
          }
        >
          Clear browsing data
        </ActionButton>
      </SRow>
      {on && settings?.kaiAllowed && <AppCommands />}
    </>
  );
}

/** The command that starts each folder's app, for Kai to start in its worktree and open in the pane. */
function AppCommands() {
  const bridge = desktopDevServers();
  const runners = useDesktopRunners();
  const [saved, setSaved] = useState<Record<string, DevCommand> | null>(null);
  useEffect(() => {
    let live = true;
    void bridge?.list().then((found) => live && setSaved(found));
    return () => {
      live = false;
    };
  }, [bridge]);
  if (!bridge) return null;
  return (
    <div className="sblock">
      <h2>Start your app for {CODING_AGENT.name}</h2>
      <p className="faint" style={{ marginTop: 0 }}>
        On a turn coding on this computer, {CODING_AGENT.name} can start your app in its own copy of the repository with the command you save here, and open it
        in the browser to check its change. {CODING_AGENT.name} can't change the command, but the command runs the code {CODING_AGENT.name} just wrote, on this
        computer and without a sandbox, so it can read and change your files like any program you run: save one only for a project you trust it to run. Its
        environment carries none of your keys or tokens, and it stops when the turn ends.
      </p>
      {!runners.length ? (
        <p className="muted">No folders code on this computer yet. Pick one when you start a coding session on this computer.</p>
      ) : (
        runners.map((runner) => (
          <AppCommand
            key={runner.folder}
            folder={runner.folder}
            label={runner.projectKey}
            saved={saved?.[runner.folder] ?? null}
            loading={saved === null}
            onSave={async (next) => setSaved(await bridge.save(runner.folder, next))}
          />
        ))
      )}
    </div>
  );
}

function AppCommand({
  folder,
  label,
  saved,
  loading,
  onSave,
}: {
  folder: string;
  label: string;
  saved: DevCommand | null;
  loading: boolean;
  onSave: (next: DevCommand | null) => Promise<void>;
}) {
  const [command, setCommand] = useState(saved?.command ?? "");
  const [port, setPort] = useState(saved?.port ? String(saved.port) : "");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setCommand(saved?.command ?? "");
    setPort(saved?.port ? String(saved.port) : "");
  }, [saved?.command, saved?.port]);
  const changed = command.trim() !== (saved?.command ?? "") || port.trim() !== (saved?.port ? String(saved.port) : "");
  const portNumber = port.trim() ? Number(port.trim()) : null;
  const badPort = portNumber !== null && !(Number.isInteger(portNumber) && portNumber >= 1024 && portNumber <= 65535);
  const send = async (next: DevCommand | null, done: string) => {
    setBusy(true);
    try {
      await onSave(next);
      toast(done);
    } catch (error) {
      toast(error instanceof Error ? error.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, "") : "The command couldn't be saved");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="srow" style={{ alignItems: "flex-start" }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="t">{label}</div>
        <div className="d mono trunc" title={folder}>
          {folder}
        </div>
        <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <DesignInput
            className="input mono"
            style={{ flex: "1 1 260px", minWidth: 0 }}
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="pnpm install && pnpm dev"
            aria-label={`Command that starts ${label}'s app`}
            disabled={loading || busy}
            spellCheck={false}
          />
          <DesignInput
            className="input mono"
            style={{ width: 110 }}
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="Any port"
            inputMode="numeric"
            aria-label={`Port ${label}'s app listens on`}
            aria-invalid={badPort}
            disabled={loading || busy}
          />
        </div>
        <div className="d" style={{ marginTop: 6 }}>
          {badPort
            ? "The port is a number from 1024 to 65535."
            : "Leave the port empty if the app reads the PORT variable; give it if the app always listens on one port."}
        </div>
      </div>
      <div className="row" style={{ gap: 6, marginTop: 22 }}>
        <ActionButton
          className="btn btn-sm"
          disabled={loading || busy || badPort || !command.trim() || !changed}
          onClick={() => void send({ command: command.trim(), port: portNumber }, `${label}'s command is saved`)}
        >
          Save
        </ActionButton>
        {saved && (
          <ActionButton className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void send(null, `${label}'s command is removed`)}>
            Remove
          </ActionButton>
        )}
      </div>
    </div>
  );
}

function Body({ sec }: { sec: string }) {
  if (sec === "appearance" || sec === "shortcuts") sec = "preferences";
  const d = D();
  const Pr = S.prefs;
  if (isLive() && sec.startsWith("notif-")) return <LiveNotifs sec={sec} />;
  switch (sec) {
    case "workspace":
      return <Workspace />;
    case "datetime":
      return (
        <>
          <SRow t="Time zone" d="Used for due dates and reminders.">
            <Sel
              k="tz"
              v={Pr.tz}
              opts={[
                "(GMT-08:00) Pacific Time",
                "(GMT-07:00) Pacific Time",
                "(GMT-05:00) Eastern Time",
                "(GMT+00:00) London",
                "(GMT+01:00) Berlin",
                "(GMT+08:00) Singapore",
              ]}
            />
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
            {canInvite() && (
              <ActionButton className="btn btn-primary" onClick={invite}>
                <Ic n="user-plus" s={14} />
                Invite member
              </ActionButton>
            )}
            <ActionButton className="btn btn-secondary" onClick={() => go("members")}>
              Open member directory
            </ActionButton>
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
                <ActionButton className="ibtn ibtn-sm" onClick={(e) => openPop(e.currentTarget, "ctx", { ctx: "member", id: m.id })} aria-label="Options">
                  <Ic n="ellipsis" s={14} />
                </ActionButton>
              </div>
            ))}
          </div>
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
                ["overview", "Overview"],
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
                    <ActionButton className="btn btn-secondary btn-sm" onClick={() => restoreProject(p.id)}>
                      Restore
                    </ActionButton>
                  </div>
                </div>
              ))
            ) : (
              <p className="faint" style={{ padding: "12px 0" }}>
                No archived projects. Archived projects are hidden from the sidebar but keep all their tasks.
              </p>
            )}
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
            <SRow t="Start coding" d="Ask Kai, the coding agent, to work on a task.">
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
    case "models":
      return <MyModels />;
    case "my-models":
      return <MyModels />;
    case "my-agents":
      return <MyAgents />;
    case "rules":
      return <Rules />;
    case "automations":
      return <Automations />;
    case "github":
      return <GitHub />;
    case "sandbox":
      return <SandboxNetworkSettings />;
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
    case "notif-mentions":
      return (
        <>
          <SRow t="@mentions in comments, chat, and descriptions">
            <NTog k="mention_all" />
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
          <SRow t="Kai's turns" d="When a coding turn you asked for opens or updates its pull request, finishes without changes, or fails.">
            <NTog k="coding" def />
          </SRow>
        </>
      );
    case "profile":
      return <Profile />;
    case "preferences":
      return (
        <>
          <div className="gh" style={{ marginTop: 0 }}>
            Appearance
          </div>
          <div className="sblock">
            <h2>Theme</h2>
            <ThemeCards />
          </div>
          <div className="sblock">
            <h2>Accent color</h2>
            <SRow t="Accent" d="Used for primary buttons, focus rings, and selection.">
              <div className="swatches" role="radiogroup" aria-label="Accent color">
                {ACCENTS.map(([k, c]) => (
                  <button
                    key={k}
                    className={`sw ${Pr.accent === k ? "on" : ""}`}
                    style={css({ "--c": c })}
                    role="radio"
                    aria-checked={Pr.accent === k}
                    onClick={() => setPref("accent", k)}
                    aria-label={k}
                    data-tip={k[0]!.toUpperCase() + k.slice(1)}
                  >
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
          <div className="gh">Personal defaults</div>
          <CodeModeSettings />
          <SRow t="Open on launch" d="The page you see when dotrix opens.">
            <Sel
              k="home"
              v={Pr.home}
              opts={[
                ["home", "Home"],
                ["mytasks", tasksLabel()],
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
          <div className="gh">Keyboard shortcuts</div>
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
    case "browser":
      return <BrowserSettingsPage />;
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
                <ActionButton
                  className="btn btn-secondary btn-sm"
                  onClick={() => (mutate(() => (d.sessions = d.sessions.filter((x) => x !== s))), toast("Signed out"))}
                >
                  Sign out
                </ActionButton>
              )}
            </SRow>
          ))}
          <div style={{ marginTop: 16 }}>
            <ActionButton
              className="btn btn-danger-ghost"
              disabled={d.sessions.length < 2}
              onClick={() => (mutate(() => (d.sessions = d.sessions.filter((x) => x.cur))), toast("Signed out of all other sessions"))}
            >
              Sign out of all other sessions
            </ActionButton>
          </div>
          <div className="sblock">
            <h2>Tokens</h2>
            <p className="muted" style={{ fontSize: 13 }}>
              Let something other than this browser act as you: the CLI after <span className="mono">dotrix login</span>, or a script or CI job.
            </p>
            {[
              ["terminal", "dotrix CLI on MacBook Pro", "last used 2 hours ago · expires Jan 3"],
              ["key-round", "CI (dtx_…7f3a)", "last used yesterday · expires Dec 11"],
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
                <ActionButton className="btn btn-secondary btn-sm" onClick={() => toast("Revoked")}>
                  Revoke
                </ActionButton>
              </SRow>
            ))}
          </div>
        </>
      );
  }
  return <Empty icon="file-question" title="Page not found" text="That settings page doesn't exist." />;
}

const LEADS: Record<string, string> = {
  workspace: "Your workspace name, address, and identity.",
  language: "Language and regional formats.",
  datetime: "How dates and times appear across the workspace.",
  members: `people have access to this workspace.`,
  projects: "Defaults for new projects and archived work.",
  permissions: "Control what each role can do.",
  agents: "The agents every project uses: what they may do, their model, and their instructions. Versioned and audited.",
  rules: "Rules every agent follows, and skills they can use, across every project.",
  automations: "Agents that run on a schedule or when something happens. Their changes still wait for approval.",
  github: "The GitHub App's installations, and the repository each project reads code from.",
  sandbox: "The hosts Kai's sandboxes may reach besides the model API. Owners and admins; every change is audited.",
  audit: "Everything people and agents changed, who asked, and who approved.",
  "notif-email": "Choose what reaches you, and where.",
  profile: "How you appear to others in the workspace.",
  preferences: "Personal defaults for how you work.",
  "my-models": "Your own model keys and the model you start conversations on.",
  "my-agents": "How you like each agent to work, for the conversations you start. Only you see these.",
  password: "Use a long password you don't use anywhere else.",
  sessions: "Browsers and apps signed in to your account, and the tokens that act as you.",
  browser: "The Browser pane beside a coding session in the desktop app. These settings are this computer's.",
};

// Old sec ids fold into a page: Agents holds Rules and Automations, Notifications holds the
// four notif- pages, Preferences holds Appearance and Shortcuts (normalized inside Body).
const SEC_PAGE: Record<string, string> = {
  rules: "agents",
  automations: "agents",
  "notif-mentions": "notif-email",
  "notif-assign": "notif-email",
  "notif-agents": "notif-email",
  appearance: "preferences",
  shortcuts: "preferences",
};
const SEC_TABS: Record<string, [string, string][]> = {
  agents: [
    ["agents", "Agents"],
    ["rules", "Rules and skills"],
    ["automations", "Automations"],
  ],
  "notif-email": [
    ["notif-email", "Email"],
    ["notif-mentions", "Mentions"],
    ["notif-assign", "Task assignments"],
    ["notif-agents", "Agents"],
  ],
};

/** Pages only an organisation has. */
const TEAM_ONLY = new Set(["members", "permissions"]);

const ITEM_NEEDS: Record<string, Perm> = {
  workspace: "workspace:manage",
  permissions: "workspace:manage",
  sandbox: "workspace:manage",
};

export function Settings() {
  const { items: members } = useMembers();
  const { params } = useRoute();
  const asked = params.sec || S.ui.settings || "profile";
  const renamed = asked === "devices" ? "sessions" : asked === "models" ? "my-models" : asked;
  // A personal workspace is just yours: no members or roles to manage (an old link opens your profile).
  const sec = personal() && TEAM_ONLY.has(renamed) ? "profile" : renamed;
  const admin = allowed("workspace:manage");
  // Pages only some people may open: shown to them alone (the API refuses the rest anyway).
  // The Browser pane is the desktop app's: its page is listed only there.
  const shown = (k: string) =>
    (ITEM_NEEDS[k] ? allowed(ITEM_NEEDS[k]) : true) && !(personal() && TEAM_ONLY.has(k)) && (k !== "browser" || Boolean(desktopBrowser()));
  const page = SEC_PAGE[sec] ?? sec;
  const title = SET_NAV.flatMap((g) => g[1]).find((x) => x[0] === page);
  const lead = sec === "members" ? `${members.length} ${LEADS.members}` : LEADS[page];
  const groups = SET_NAV.filter(([, items, adminOnly]) => (!adminOnly || admin) && items.some(([k]) => shown(k)));
  const openSection = (section: string) => {
    S.ui.settings = section;
    S.ui.agentSel = null;
    go("settings", { sec: section });
  };
  return (
    <div className="set">
      <label className="set-section-picker" htmlFor="settings-section">
        <span className="label">Settings section</span>
        <select id="settings-section" className="select" value={page} onChange={(event) => openSection(event.target.value)}>
          {groups.map(([group, items]) => (
            <optgroup key={group} label={group}>
              {items
                .filter(([key]) => shown(key))
                .map(([key, name]) => (
                  <option key={key} value={key}>
                    {name}
                  </option>
                ))}
            </optgroup>
          ))}
        </select>
      </label>
      <nav className="set-nav" aria-label="Settings">
        {groups.map(([g, items]) => (
          <div key={g} style={{ display: "contents" }}>
            <div className="gh">{g}</div>
            {items
              .filter(([k]) => shown(k))
              .map(([k, n, i]) => (
                <button
                  key={k}
                  className={`sitem ${sec === k || page === k ? "on" : ""}`}
                  aria-current={sec === k || page === k ? "page" : undefined}
                  onClick={() => openSection(k)}
                >
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
          {SEC_TABS[page] && (
            <div className="seg" style={{ marginBottom: 14 }}>
              {SEC_TABS[page].map(([k, n]) => (
                <button key={k} className={sec === k ? "on" : ""} onClick={() => ((S.ui.settings = k), go("settings", { sec: k }))}>
                  {n}
                </button>
              ))}
            </div>
          )}
          <Body sec={sec} />
        </div>
      </div>
    </div>
  );
}
