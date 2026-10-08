// Gr8r's design system and system states pages (gr8r-studio/src/pages/design-system.js), with
// dotrix's own pieces: a proposed change, a plan to steer, and the chat's "working" line.
import type { CSSProperties, ReactNode } from "react";

import { openTask, setPref } from "../core/actions";
import { LABELS, PCOLORS, PRIOS, STATUSES } from "../core/constants";
import { Ic } from "../core/icons";
import { archiveProject, confirmDlg, delProject, delTask, newProject, newTask, removeMember, toggleOffline } from "../core/more";
import { go } from "../core/nav";
import { dOff } from "../core/utils";
import { S, allTasks, task } from "../data/store";
import { ChangeCard } from "../components/Changes";
import { MiniRow } from "../components/TaskList";
import { openPalette } from "../overlays/Palette";
import { Av, AvStack, Empty, Lbl, PStatus, PrPill, ProgBar, StPill, sk } from "../ui/helpers";
import { toast } from "../ui/toast";
import { KCard } from "../views/Board";

const css = (o: Record<string, string | number>) => o as CSSProperties;

function Sec({ title, sub, children, style }: { title: string; sub?: string; children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="ds-sec" style={style}>
      <h2>
        {title} {sub && <span>{sub}</span>}
      </h2>
      {children}
    </div>
  );
}

export function DesignSystem() {
  const states = ["", "state-hover", "state-active", "state-focus", "dis", "is-loading"];
  const stN = ["Default", "Hover", "Active", "Focus", "Disabled", "Loading"];
  const t3 = task("t3") || allTasks()[0]!;
  return (
    <div className="page">
      <div className="ph">
        <div>
          <h1>Design system</h1>
          <p>Tokens and components that make up dotrix. Switch themes to see both palettes.</p>
        </div>
        <div className="acts">
          <div className="seg">
            {(
              [
                ["light", "sun"],
                ["dark", "moon"],
                ["system", "monitor"],
              ] as const
            ).map(([k, i]) => (
              <button key={k} className={S.prefs.theme === k ? "on" : ""} onClick={() => setPref("theme", k)}>
                <Ic n={i} s={13} />
                {k[0]!.toUpperCase() + k.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>
      <Sec title="Color" sub="Semantic tokens, redefined per theme" style={{ marginTop: 8 }}>
        <div className="ds-grid">
          {[
            ["Background", "--bg"],
            ["Sidebar", "--bg-side"],
            ["Surface", "--surface"],
            ["Surface 2", "--surface-2"],
            ["Surface 3", "--surface-3"],
            ["Border", "--border"],
            ["Border strong", "--border-strong"],
            ["Text", "--text"],
            ["Text 2", "--text-2"],
            ["Text 3", "--text-3"],
            ["Accent", "--acc"],
            ["Success", "--green"],
            ["Warning", "--amber"],
            ["Error", "--red"],
          ].map(([n, v]) => (
            <div key={v} className="ds-tok">
              <div className="c" style={css({ "--c": `var(${v})` })} />
              <div className="n">
                <span>{n}</span>
                <code>{v}</code>
              </div>
            </div>
          ))}
        </div>
      </Sec>
      <Sec title="Status & priority" sub="Always paired with text or a tooltip">
        <div className="ds-row">
          {STATUSES.map((s) => (
            <span key={s.id} className="pillbtn bordered">
              <StPill st={s.id} />
            </span>
          ))}
        </div>
        <div className="ds-row">
          {PRIOS.map((p) => (
            <span key={p.id} className="pillbtn bordered">
              <PrPill p={p.id} />
            </span>
          ))}
        </div>
        <div className="ds-row">
          {LABELS.map((l) => (
            <Lbl key={l.id} id={l.id} />
          ))}
        </div>
      </Sec>
      <Sec title="Typography" sub="Geist · Geist Mono">
        <div className="panel" style={{ padding: "4px 16px" }}>
          {(
            [
              ["Page title", "var(--fs-2xl)", 600, "Website Redesign"],
              ["Section title", "var(--fs-xl)", 600, "Upcoming deadlines"],
              ["Subsection", "var(--fs-md)", 600, "Subtasks"],
              ["Body", "var(--fs)", 400, "Low-fidelity wireframes for the new homepage."],
              ["Secondary", "var(--fs-sm)", 400, "Updated 38 minutes ago"],
              ["Metadata", "var(--fs-xs)", 500, "WEB-109 · Due tomorrow"],
              ["Label", "var(--fs-2xs)", 600, "WORKSPACE"],
            ] as const
          ).map(([n, s, w, ex]) => (
            <div key={n} className="row" style={{ padding: "10px 0", borderBottom: "1px solid var(--divider)", gap: 16 }}>
              <span className="faint" style={{ width: 110, fontSize: 12, flexShrink: 0 }}>
                {n}
              </span>
              <span
                className="grow trunc"
                style={{ fontSize: s, fontWeight: w, ...(n === "Label" ? { letterSpacing: ".06em", color: "var(--text-3)" } : n === "Secondary" || n === "Metadata" ? { color: "var(--text-2)" } : {}) }}
              >
                {ex}
              </span>
              <code className="mono faint" style={{ fontSize: 11 }}>
                {s.replace("var(", "").replace(")", "")} / {w}
              </code>
            </div>
          ))}
        </div>
      </Sec>
      <Sec title="Spacing, radius, elevation" sub="4pt scale">
        <div className="grid2" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div className="panel" style={{ padding: 14 }}>
            {[1, 2, 3, 4, 5, 6, 8, 10, 12].map((n) => (
              <div key={n} className="row" style={{ height: 22, fontSize: 12 }}>
                <code className="mono faint" style={{ width: 56 }}>
                  --s-{n}
                </code>
                <span style={{ height: 8, width: `var(--s-${n})`, background: "var(--acc)", borderRadius: 2, opacity: 0.7 }} />
                <span className="faint">{n * 4}px</span>
              </div>
            ))}
          </div>
          <div className="panel" style={{ padding: 14, display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
            {(
              [
                ["xs", 4],
                ["sm", 6],
                ["", 8],
                ["lg", 10],
              ] as const
            ).map(([k, v]) => (
              <div key={v} className="col" style={{ alignItems: "center", gap: 6, fontSize: 11.5 }}>
                <span style={{ width: 48, height: 48, border: "1.5px solid var(--border-strong)", borderRadius: `var(--r${k ? "-" + k : ""})`, background: "var(--surface-2)" }} />
                <span className="faint">{v}px</span>
              </div>
            ))}
            {[
              ["card", "--shadow-card"],
              ["pop", "--shadow-pop"],
              ["drag", "--shadow-drag"],
            ].map(([n, v]) => (
              <div key={n} className="col" style={{ alignItems: "center", gap: 6, fontSize: 11.5 }}>
                <span style={{ width: 48, height: 48, borderRadius: 8, background: "var(--surface)", boxShadow: `var(${v})` }} />
                <span className="faint">{n}</span>
              </div>
            ))}
          </div>
        </div>
      </Sec>
      <Sec title="Buttons" sub="Primary · Secondary · Ghost · Destructive · Icon">
        {[
          ["btn-primary", "Create task"],
          ["btn-secondary", "Share"],
          ["btn-ghost", "Filter"],
          ["btn-danger", "Delete"],
        ].map(([c, l]) => (
          <div key={c} className="ds-row">
            <span className="lab">{c!.replace("btn-", "")}</span>
            {states.map((s, i) => (
              <span key={s} className="col" style={{ gap: 4, alignItems: "flex-start" }}>
                <span className="faint" style={{ fontSize: 11 }}>
                  {stN[i]}
                </span>
                <button className={`btn ${c} ${s}`} disabled={s === "dis"}>
                  {l}
                </button>
              </span>
            ))}
          </div>
        ))}
        <div className="ds-row">
          <span className="lab">icon</span>
          {["plus", "list-filter", "ellipsis", "star", "share-2", "settings"].map((i, k) => (
            <button key={i} className={`ibtn ${k === 1 ? "on" : ""}`} aria-label={i} data-tip={i}>
              <Ic n={i} s={16} />
            </button>
          ))}
          <button className="ibtn" disabled aria-label="Disabled">
            <Ic n="trash-2" s={16} />
          </button>
          <span className="faint" style={{ fontSize: 11.5 }}>
            Sizes:
          </span>
          <button className="btn btn-secondary btn-sm">Small</button>
          <button className="btn btn-secondary">Medium</button>
          <button className="btn btn-secondary btn-lg">Large</button>
        </div>
      </Sec>
      <Sec title="Inputs">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(230px,1fr))", gap: 14 }} className="panel">
          {(
            [
              ["Text", <input key="1" className="input" placeholder="Task name" />],
              ["Focus", <input key="2" className="input" defaultValue="Homepage wireframes" style={{ borderColor: "var(--acc)", boxShadow: "0 0 0 3px var(--accent-soft)" }} />],
              [
                "Error",
                <>
                  <input className="input is-error" defaultValue="alex@" />
                  <span className="err">
                    <Ic n="circle-alert" s={12} />
                    Enter a valid email address
                  </span>
                </>,
              ],
              ["Disabled", <input key="4" className="input" defaultValue="hello@gr8rstudio.com" disabled />],
              [
                "Search",
                <div className="inwrap">
                  <Ic n="search" s={13} />
                  <input className="input" placeholder="Search tasks" />
                  <span className="kbd">/</span>
                </div>,
              ],
              [
                "Select",
                <select className="select" defaultValue="In Progress">
                  <option>In Progress</option>
                  <option>Review</option>
                </select>,
              ],
              [
                "Multi-select",
                <div className="input" style={{ height: "auto", minHeight: 30, display: "flex", flexWrap: "wrap", gap: 4, padding: 4 }}>
                  <Lbl id="design" />
                  <Lbl id="frontend" />
                  <Lbl id="qa" />
                  <span className="faint" style={{ fontSize: 12, padding: "2px 4px" }}>
                    Add…
                  </span>
                </div>,
              ],
              ["Date", <input type="date" className="input" defaultValue={dOff(3)} />],
              ["Time", <input type="time" className="input" defaultValue="14:30" />],
              [
                "Checkbox · Radio · Toggle",
                <div className="row" style={{ gap: 14 }}>
                  <input type="checkbox" className="check" defaultChecked aria-label="c1" />
                  <input type="checkbox" className="check" aria-label="c2" />
                  <input type="checkbox" className="check round" defaultChecked aria-label="c3" />
                  <input type="radio" className="radio" name="dsr" defaultChecked aria-label="r1" />
                  <input type="radio" className="radio" name="dsr" aria-label="r2" />
                  <input type="checkbox" className="toggle" defaultChecked aria-label="t1" />
                  <input type="checkbox" className="toggle" aria-label="t2" />
                </div>,
              ],
              ["Textarea", <textarea className="textarea" rows={2} defaultValue="Add a description…" />],
              [
                "Rich text",
                <div className="rte" style={{ borderColor: "var(--border)" }}>
                  <div className="rte-tb" style={{ opacity: 1, borderBottomColor: "var(--divider)" }}>
                    {["bold", "italic", "list", "list-ordered", "heading", "link"].map((i) => (
                      <span key={i} className="ibtn ibtn-xs">
                        <Ic n={i} s={13} />
                      </span>
                    ))}
                  </div>
                  <div className="rte-body" style={{ minHeight: 40 }}>
                    <b>Bold</b>, <i>italic</i>, and lists.
                  </div>
                </div>,
              ],
            ] as [string, ReactNode][]
          ).map(([n, h]) => (
            <div key={n} className="field" style={{ padding: 14 }}>
              <span className="label">{n}</span>
              {h}
            </div>
          ))}
        </div>
      </Sec>
      <Sec title="Navigation">
        <div className="grid2" style={{ gridTemplateColumns: "260px 1fr" }}>
          <div className="side" style={{ border: "1px solid var(--border)", borderRadius: "var(--r-lg)", padding: 8, height: "auto" }}>
            <button className="sitem" onClick={() => go("home")}>
              <Ic n="house" s={16} />
              <span>Home</span>
            </button>
            <button className="sitem on">
              <Ic n="inbox" s={16} />
              <span>Inbox (active)</span>
              <span className="ct dotc">3</span>
            </button>
            <button className="sitem state-hover">
              <Ic n="circle-check" s={16} />
              <span>My Tasks (hover)</span>
            </button>
            <div className="sitem">
              <span className="pico" style={css({ "--c": PCOLORS.indigo! })}>
                <Ic n="globe" s={12} />
              </span>
              <span>Website Redesign</span>
              <span className="sdot" style={{ background: "var(--blue)" }} />
            </div>
          </div>
          <div className="col" style={{ gap: 14 }}>
            <nav className="crumbs" style={{ border: "1px solid var(--border)", borderRadius: "var(--r)", padding: 6 }}>
              <button>Gr8r Studio</button>
              <span className="sep">/</span>
              <button>Projects</button>
              <span className="sep">/</span>
              <button className="cur">Website Redesign</button>
            </nav>
            <div className="tabs">
              {["Overview", "Board", "List", "Table"].map((t, i) => (
                <button key={t} className={`tab ${i === 1 ? "on" : ""}`}>
                  {t}
                </button>
              ))}
            </div>
            <div className="row">
              <div className="seg">
                <button className="on">
                  <Ic n="layout-grid" s={13} />
                  Grid
                </button>
                <button>
                  <Ic n="list" s={13} />
                  List
                </button>
                <button>
                  <Ic n="table-2" s={13} />
                  Table
                </button>
              </div>
              <span className="chip">
                <Ic n="circle-dot" s={12} />
                <b>Status</b> is <span>In Progress</span>
                <span className="ibtn">
                  <Ic n="x" s={12} />
                </span>
              </span>
            </div>
          </div>
        </div>
      </Sec>
      <Sec title="Data display">
        <div className="grid2" style={{ gridTemplateColumns: "300px 1fr" }}>
          <div style={{ background: "var(--sunken)", padding: 10, borderRadius: "var(--r-lg)" }}>
            <KCard t={t3} />
          </div>
          <div className="col" style={{ gap: 12 }}>
            <div className="ds-row">
              <span className="lab">Avatar</span>
              {["m1", "m2", "m3"].map((i) => (
                <Av key={i} id={i} cls="sm" />
              ))}
              <Av id="m4" />
              <Av id="m5" cls="md" />
              <Av id="m6" cls="lg" />
              <Av id={null} />
              <Av id="research" cls="md" />
              <AvStack ids={["m1", "m2", "m3", "m4", "m5", "m6"]} max={4} cls="md" />
            </div>
            <div className="ds-row">
              <span className="lab">Badge</span>
              <span className="badge">Default</span>
              <span className="badge accent">Accent</span>
              <span className="badge green">
                <span className="dot" />
                Active
              </span>
              <span className="badge amber">
                <span className="dot" />
                Invited
              </span>
              <span className="badge red">3 overdue</span>
              <PStatus s="active" />
              <PStatus s="risk" />
            </div>
            <div className="ds-row">
              <span className="lab">Progress</span>
              <span style={{ width: 200, display: "flex" }}>
                <ProgBar v={64} />
              </span>
              <span style={{ width: 120, display: "flex" }}>
                <ProgBar v={100} cls="green" />
              </span>
              <span style={{ width: 120, display: "flex" }}>
                <ProgBar v={30} cls="red" />
              </span>
            </div>
            <div className="panel" style={{ overflow: "hidden" }}>
              {allTasks()
                .slice(0, 2)
                .map((t) => (
                  <MiniRow key={t.id} t={t} />
                ))}
            </div>
          </div>
        </div>
      </Sec>
      <Sec title="Agents" sub="Proposed changes and plans wait for a person">
        <div className="grid2" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <ChangeCard ch={{ id: "ds-c1", kind: "write_file", title: "roadmap.md", diff: " ## Next\n-Launch in Q3\n+Launch on Oct 28\n+Beta for 20 customers first", status: "pending" }} />
          <ChangeCard ch={{ id: "ds-c2", kind: "checkpoint", title: "Plan: pricing research", plan: ["Read our pricing notes", "Compare five competitors", "Recommend tiers, with sources"], status: "pending" }} />
        </div>
        <div className="row muted" style={{ gap: 8, fontSize: 12.5, marginTop: 10 }}>
          <span className="chat-typing">
            <i />
            <i />
            <i />
          </span>
          Research agent is searching the web…
        </div>
      </Sec>
      <Sec title="Feedback">
        <div className="col" style={{ gap: 8, marginBottom: 12 }}>
          <div className="alert info">
            <Ic n="info" s={15} />
            <span>
              <b>Heads up.</b> Timeline dependencies are shown as dashed when out of order.
            </span>
          </div>
          <div className="alert ok">
            <Ic n="circle-check" s={15} />
            <span>
              Project archived. <button className="link">Undo</button>
            </span>
          </div>
          <div className="alert warn">
            <Ic n="triangle-alert" s={15} />
            <span>3 tasks due this week are not started.</span>
          </div>
          <div className="alert danger">
            <Ic n="circle-alert" s={15} />
            <span>
              Your changes couldn&apos;t be saved. <button className="link">Try again</button>
            </span>
          </div>
        </div>
        <div className="ds-row">
          <span className="lab">Triggers</span>
          <button className="btn btn-secondary" onClick={() => toast("Task created", { action: "Undo", onAction: () => {} })}>
            Toast
          </button>
          <button className="btn btn-secondary" onClick={() => toast("Your changes couldn't be saved.", { kind: "err", action: "Try again", onAction: () => {} })}>
            Error toast
          </button>
          <button className="btn btn-secondary" data-tip="Tooltips pair with icon buttons">
            Tooltip
          </button>
          <button className="btn btn-secondary" onClick={() => newTask()}>
            Modal
          </button>
          <button className="btn btn-secondary" onClick={() => openTask("t3")}>
            Drawer
          </button>
          <button className="btn btn-secondary" onClick={() => confirmDlg({ title: "Discard changes?", body: "Your edits to this task will be lost.", ok: "Discard", danger: true, run: () => {} })}>
            Confirmation
          </button>
          <button className="btn btn-secondary" onClick={() => openPalette()}>
            Command menu
          </button>
        </div>
      </Sec>
      <Sec title="Iconography" sub="Lucide · 1.8px stroke · 12–18px">
        <div className="panel" style={{ padding: 14, display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(40px,1fr))", gap: 6, color: "var(--text-2)" }}>
          {["house", "inbox", "circle-check", "star", "search", "bell", "folder-kanban", "list-checks", "calendar", "chart-gantt", "users", "activity", "settings", "plus", "list-filter", "arrow-up-down", "rows-3", "share-2", "ellipsis", "paperclip", "message-square", "tag", "link", "copy", "pencil", "trash-2", "archive", "upload", "repeat", "timer", "git-branch", "lock", "eye", "at-sign", "sun", "moon", "sparkles", "bot", "book-open", "shield-check"].map((i) => (
            <span key={i} style={{ height: 36, display: "grid", placeItems: "center" }} title={i}>
              <Ic n={i} s={17} />
            </span>
          ))}
        </div>
      </Sec>
    </div>
  );
}

function Card({ cap, icon, children }: { cap: string; icon: string; children: ReactNode }) {
  return (
    <div className="panel">
      <div className="cap">
        <Ic n={icon} s={13} />
        {cap}
      </div>
      {children}
    </div>
  );
}
const skRows = (n: number) =>
  Array.from({ length: n }, (_, i) => (
    <div key={i} className="row" style={{ height: 36, gap: 10, borderBottom: "1px solid var(--divider)" }}>
      {sk("14px", 14, { borderRadius: "50%" })}
      {sk(`${40 + ((i * 17) % 40)}%`, 10)}
      <span className="sp" />
      {sk("48px", 10)}
      {sk("18px", 18, { borderRadius: "50%" })}
    </div>
  ));

export function SystemStates() {
  return (
    <div className="page wide" style={{ maxWidth: 1240 }}>
      <div className="ph">
        <div>
          <h1>System states</h1>
          <p>Empty, loading, error, and confirmation states used throughout dotrix.</p>
        </div>
        <div className="acts">
          <button className="btn btn-secondary" onClick={toggleOffline}>
            <Ic n={S.ui.offline ? "wifi" : "wifi-off"} s={14} />
            {S.ui.offline ? "Go back online" : "Simulate offline"}
          </button>
        </div>
      </div>
      <h2 className="sec" style={{ margin: "8px 0 10px" }}>
        Empty states
      </h2>
      <div className="states-grid">
        <Card cap="No projects" icon="folder-kanban">
          <Empty icon="folder-kanban" title="No projects yet" text="Create your first project to start organizing your work.">
            <button className="btn btn-primary btn-sm" onClick={newProject}>
              <Ic n="plus" s={14} />
              Create project
            </button>
          </Empty>
        </Card>
        <Card cap="No tasks" icon="list-checks">
          <Empty icon="list-checks" title="No tasks here" text="Add a task to get things moving.">
            <button className="btn btn-primary btn-sm" onClick={() => newTask()}>
              <Ic n="plus" s={14} />
              Add task
            </button>
          </Empty>
        </Card>
        <Card cap="No notifications" icon="bell">
          <Empty icon="bell-off" title="You're all caught up." text="Nothing waits for you. When an agent wants to change something, it shows up here." />
        </Card>
        <Card cap="No search results" icon="search">
          <Empty icon="search-x" title="No results found" text="Nothing matches “brand guidlines”. Check the spelling or try a broader term.">
            <button className="btn btn-secondary btn-sm">Clear search</button>
          </Empty>
        </Card>
      </div>
      <h2 className="sec" style={{ margin: "28px 0 10px" }}>
        Loading states
      </h2>
      <div className="states-grid">
        <Card cap="List / table rows" icon="rows-3">
          <div style={{ padding: "4px 10px" }}>{skRows(5)}</div>
        </Card>
        <Card cap="Cards" icon="layout-grid">
          <div style={{ padding: 12 }}>
            <div className="pcard" style={{ cursor: "default" }}>
              {sk("28px", 28, { borderRadius: 7 })}
              {sk("60%", 12)}
              {sk("90%", 9)}
              {sk("70%", 9)}
              {sk("100%", 4)}
            </div>
          </div>
        </Card>
        <Card cap="Board column" icon="square-kanban">
          <div style={{ padding: 12, background: "var(--sunken)" }}>
            <div className="col" style={{ gap: 6 }}>
              {[0, 1].map((i) => (
                <div key={i} className="kcard" style={{ cursor: "default" }}>
                  {sk("40%", 14)}
                  {sk("80%", 10)}
                  <div className="row">
                    {sk("40px", 9)}
                    <span className="sp" />
                    {sk("18px", 18, { borderRadius: "50%" })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
        <Card cap="Buttons & page" icon="loader">
          <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14, alignItems: "flex-start" }}>
            <div className="row">
              <button className="btn btn-primary is-loading">Saving</button>
              <button className="btn btn-secondary is-loading">Loading</button>
            </div>
            <div className="row muted" style={{ fontSize: 13 }}>
              <span style={{ width: 16, height: 16, borderRadius: "50%", border: "2px solid var(--border-strong)", borderTopColor: "var(--acc)", animation: "spin .7s linear infinite", display: "inline-block" }} />
              Loading project…
            </div>
          </div>
        </Card>
      </div>
      <h2 className="sec" style={{ margin: "28px 0 10px" }}>
        Error states
      </h2>
      <div className="states-grid">
        <Card cap="Network error" icon="wifi-off">
          <div className="empty-state err sm">
            <div className="glyph">
              <Ic n="wifi-off" s={20} />
            </div>
            <h3 className="es-h">You&apos;re offline</h3>
            <p>Check your connection. We&apos;ll sync your changes when you&apos;re back.</p>
            <button className="btn btn-secondary btn-sm" onClick={() => toast("Back online")}>
              <Ic n="refresh-cw" s={13} />
              Try again
            </button>
          </div>
        </Card>
        <Card cap="Failed to load" icon="cloud-alert">
          <div className="empty-state err sm">
            <div className="glyph">
              <Ic n="cloud-alert" s={20} />
            </div>
            <h3 className="es-h">Something went wrong.</h3>
            <p>This view failed to load. Your data is safe.</p>
            <button className="btn btn-secondary btn-sm" onClick={() => toast("Loaded")}>
              Try again
            </button>
          </div>
        </Card>
        <Card cap="Agent run failed" icon="bot">
          <div className="empty-state err sm">
            <div className="glyph">
              <Ic n="bot" s={20} />
            </div>
            <h3 className="es-h">The agent stopped</h3>
            <p>It reached the run&apos;s token budget. Approved changes stay; ask again to continue.</p>
            <button className="btn btn-secondary btn-sm" onClick={() => go("chat")}>
              Open Chat
            </button>
          </div>
        </Card>
        <Card cap="Permission denied" icon="lock">
          <div className="empty-state sm">
            <div className="glyph">
              <Ic n="lock" s={20} />
            </div>
            <h3 className="es-h">You don&apos;t have access</h3>
            <p>Customer Portal is private. Request access from Marcus Lee.</p>
            <button className="btn btn-secondary btn-sm" onClick={() => go("project", { id: "CP" })}>
              Open example
            </button>
          </div>
        </Card>
        <Card cap="Page not found" icon="file-question">
          <div className="empty-state sm">
            <div className="glyph">
              <Ic n="file-question" s={20} />
            </div>
            <h3 className="es-h">Page not found</h3>
            <p>The page was moved, deleted, or never existed.</p>
            <button className="btn btn-secondary btn-sm" onClick={() => go("project", { id: "NOWHERE" })}>
              Open example
            </button>
          </div>
        </Card>
        <Card cap="Form validation" icon="text-cursor-input">
          <div style={{ padding: 18 }} className="col">
            <div className="field">
              <label className="label" htmlFor="st-e">
                Email
              </label>
              <input className="input is-error" id="st-e" defaultValue="hello@gr8rstudio" aria-invalid="true" />
              <span className="err">
                <Ic n="circle-alert" s={12} />
                Enter a valid email, like name@company.com
              </span>
            </div>
          </div>
        </Card>
      </div>
      <h2 className="sec" style={{ margin: "28px 0 10px" }}>
        Confirmation dialogs
      </h2>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button className="btn btn-secondary" onClick={() => delProject("p5")}>
          <Ic n="trash-2" s={14} />
          Delete project
        </button>
        <button className="btn btn-secondary" onClick={() => delTask("t10")}>
          <Ic n="trash-2" s={14} />
          Delete task
        </button>
        <button className="btn btn-secondary" onClick={() => removeMember("m8")}>
          <Ic n="user-minus" s={14} />
          Remove member
        </button>
        <button className="btn btn-secondary" onClick={() => archiveProject("p7")}>
          <Ic n="archive" s={14} />
          Archive project
        </button>
      </div>
      <p className="faint" style={{ fontSize: 12.5, marginTop: 8 }}>
        These open the real dialogs. Confirming performs the action on the seeded data; use Help → Reset demo data to restore.
      </p>
    </div>
  );
}
