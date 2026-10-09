// Gr8r's command palette (gr8r-studio/src/overlays/palette.js): commands, then search over
// everything (Tab switches), and the workspace switcher. dotrix adds Chat, the agents (Chat opens
// with that agent picked), documents, and "Ask the agents" with what you typed.
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

import { openTask, setPref, toggleSide } from "../core/actions";
import { PSTAT } from "../core/constants";
import { Ic, Logo, WsLogo } from "../core/icons";
import { invite, newProject, newTask, openModal, shortcuts, signOut, switchWs } from "../core/more";
import { go } from "../core/nav";
import { effectiveDark } from "../core/theme";
import { MOD, clamp } from "../core/utils";
import { D, S, allTasks, pColor, proj, render, save, task } from "../data/store";
import { searchAll } from "../screens/Search";
import { goTasks } from "../screens/Home";
import { setPaletteOpener } from "../shell/Shell";
import { sortTasks } from "../shell/viewEngine";
import { Av, FT, Hl, StIcon } from "../ui/helpers";
import { Face } from "../ui/face";

type Item = { icon?: string; html?: ReactNode; name: string; sub?: string; r?: string; kbd?: string; run: () => void };
type Group = { name: string; items: Item[] };

export function openPalette(mode: "cmd" | "search" = "cmd", q = "") {
  S.ui.palette = { q, mode, scope: "all", hl: 0 };
  S.ui.pop = null;
  S.ui.mnav = false;
  render();
}
export function closePalette() {
  S.ui.palette = null;
  render();
}
setPaletteOpener(() => openPalette());

export function toggleDark() {
  setPref("theme", effectiveDark() ? "light" : "dark");
}

function commands(): (Item & { id: string })[] {
  return [
    { id: "c-task", name: "Create task", icon: "plus", kbd: "N", run: () => newTask() },
    { id: "c-proj", name: "Create project", icon: "folder-plus", kbd: "P", run: newProject },
    { id: "c-chat", name: "Ask the agents in Chat", icon: "message-square", run: () => go("chat", {}, { search: "new=1" }) },
    { id: "c-search", name: "Search workspace", icon: "search", kbd: "/", run: () => openPalette("search") },
    { id: "c-home", name: "Go to Home", icon: "house", kbd: "G H", run: () => go("home") },
    { id: "c-inbox", name: "Go to Inbox", icon: "inbox", kbd: "G I", run: () => go("inbox") },
    { id: "c-notif", name: "Go to Notifications", icon: "bell", kbd: "G N", run: () => go("notifications") },
    { id: "c-my", name: "Go to My Tasks", icon: "circle-check", kbd: "G T", run: () => go("mytasks") },
    { id: "c-chatgo", name: "Go to Chat", icon: "message-square", kbd: "G A", run: () => go("chat") },
    { id: "c-projs", name: "Go to Projects", icon: "folder-kanban", kbd: "G P", run: () => go("projects") },
    { id: "c-cal", name: "Go to Calendar", icon: "calendar", kbd: "G C", run: () => go("calendar") },
    { id: "c-tl", name: "Go to Timeline", icon: "chart-gantt", run: () => go("timeline") },
    { id: "c-mem", name: "Go to Members", icon: "users", kbd: "G M", run: () => go("members") },
    { id: "c-set", name: "Open settings", icon: "settings", kbd: "G S", run: () => go("settings") },
    { id: "c-agents", name: "Agents settings", icon: "bot", run: () => go("settings", { sec: "agents" }) },
    { id: "c-app", name: "Appearance settings", icon: "palette", run: () => go("settings", { sec: "appearance" }) },
    { id: "c-ws", name: "Switch workspace…", icon: "arrow-left-right", run: () => ((S.ui.palette = { q: "", mode: "ws", scope: "all", hl: 0 }), render()) },
    { id: "c-dark", name: effectiveDark() ? "Switch to light mode" : "Switch to dark mode", icon: effectiveDark() ? "sun" : "moon", kbd: MOD + " ⇧ L", run: toggleDark },
    { id: "c-inv", name: "Invite member", icon: "user-plus", run: invite },
    { id: "c-side", name: "Toggle sidebar", icon: "panel-left", kbd: "[", run: toggleSide },
    { id: "c-keys", name: "Keyboard shortcuts", icon: "keyboard", kbd: "?", run: shortcuts },
    { id: "c-out", name: "Sign out", icon: "log-out", run: signOut },
  ];
}

const agentIcon = (c: string) => <Face c={c} size={20} />;

function items(): Group[] {
  const pl = S.ui.palette!;
  const q = pl.q.trim();
  const ql = q.toLowerCase();
  const groups: Group[] = [];
  if (pl.mode === "ws")
    return [
      {
        name: "Switch workspace",
        items: D()
          .workspaces.filter((w) => !q || w.name.toLowerCase().includes(ql))
          .map((w) => ({ html: <WsLogo w={w} px={20} />, name: w.name, sub: w.plan + " plan", run: () => switchWs(w.id) })),
      },
    ];
  if (pl.mode === "cmd") {
    const cmds = commands().filter((c) => !q || c.name.toLowerCase().includes(ql));
    if (!q) {
      groups.push({ name: "Suggestions", items: cmds.slice(0, 3).concat(cmds.filter((c) => c.id === "c-dark" || c.id === "c-ws")) });
      const recent = sortTasks(
        allTasks().filter((t) => t.assignee === D().me || t.fav),
        { f: "updated", dir: 1 },
      ).slice(0, 4);
      groups.push({ name: "Recent tasks", items: recent.map((t) => ({ html: <StIcon st={t.status} />, name: t.title, sub: proj(t.project)?.name, r: t.key, run: () => openTask(t.id) })) });
      groups.push({ name: "Navigation", items: cmds.filter((c) => c.name.startsWith("Go to")) });
      return groups;
    }
    if (cmds.length) groups.push({ name: "Commands", items: cmds.slice(0, 5) });
    const ags = D().agents.filter((a) => a.name.toLowerCase().includes(ql) || a.handle.includes(ql) || "agent".startsWith(ql));
    if (ags.length) groups.push({ name: "Agents", items: ags.map((a) => ({ html: agentIcon(a.c), name: a.name, sub: `${a.role} · ${a.desc}`, run: () => go("chat", {}, { search: `new=1&agent=${a.handle}` }) })) });
  }
  const r = searchAll(q);
  const sc = pl.mode === "search" ? pl.scope : "all";
  const lim = sc === "all" ? 4 : 12;
  if (pl.mode === "search" && !q) {
    groups.push({
      name: "Recent searches",
      items: D().recentSearches.map((s) => ({
        icon: "history",
        name: s,
        run: () => {
          S.ui.palette = { ...pl, q: s, hl: 0 };
          render();
        },
      })),
    });
    groups.push({
      name: "Suggested",
      items: [
        { icon: "clock-alert", name: "Overdue tasks", run: () => goTasks("overdue") },
        { icon: "user", name: "Tasks assigned to me", run: () => go("mytasks") },
        { icon: "shield-check", name: "Changes waiting for my approval", run: () => go("notifications", {}, { search: "tab=approval" }) },
        { icon: "paperclip", name: "Files in Website Redesign", run: () => go("project", { id: "WEB", tab: "files" }) },
      ],
    });
    return groups;
  }
  if (!q) return groups;
  if (sc === "all" || sc === "tasks") groups.push({ name: "Tasks", items: r.tasks.slice(0, lim).map((t) => ({ html: <StIcon st={t.status} />, name: t.title, sub: proj(t.project)?.name, r: t.key, run: () => openTask(t.id) })) });
  if (sc === "all" || sc === "projects")
    groups.push({
      name: "Projects",
      items: r.projects.slice(0, lim).map((p) => ({ html: <span className="pdot" style={{ "--c": pColor(p) } as CSSProperties} />, name: p.name, sub: PSTAT[p.status].name, run: () => go("project", { id: p.key }) })),
    });
  if (sc === "all" || sc === "documents")
    groups.push({
      name: "Documents",
      items: r.documents.slice(0, lim).map((f) => ({ icon: "book-open", name: f.path, sub: proj(f.project)?.name, run: () => go("project", { id: proj(f.project)!.key, tab: "knowledge" }) })),
    });
  if (sc === "all" || sc === "people") groups.push({ name: "People", items: r.people.slice(0, lim).map((m) => ({ html: <Av id={m.id} cls="sm" tip={false} />, name: m.name, sub: m.title, run: () => go("member", { id: m.id }) })) });
  if (sc === "all" || sc === "files")
    groups.push({
      name: "Files",
      items: r.files.slice(0, lim).map((f) => ({ icon: (FT[f.type] || FT.other!).i, name: f.name, sub: proj(f.project)?.name, r: f.size, run: () => openModal({ type: "filePreview", file: f, tid: f.task }) })),
    });
  if (sc === "all" || sc === "comments")
    groups.push({ name: "Comments", items: r.comments.slice(0, lim).map((c) => ({ html: <Av id={c.by} cls="sm" tip={false} />, name: c.text, sub: "on " + task(c.task)?.title, run: () => openTask(c.task) })) });
  const out = groups.filter((g) => g.items.length);
  out.push({
    name: "",
    items: [
      { icon: "sparkles", name: `Ask the agents “${q}”`, run: () => go("chat", {}, { search: `q=${encodeURIComponent(q)}` }) },
      {
        icon: "search",
        name: `View all results for “${q}”`,
        run: () => {
          S.ui.searchQ = q;
          S.ui.searchCat = sc;
          if (!D().recentSearches.includes(q)) D().recentSearches.unshift(q);
          D().recentSearches = D().recentSearches.slice(0, 5);
          save();
          go("search");
        },
      },
    ],
  });
  return out;
}

let flat: Item[] = [];
export function palMove(d: number) {
  const pl = S.ui.palette!;
  pl.hl = (pl.hl + d + flat.length) % Math.max(flat.length, 1);
  render();
  requestAnimationFrame(() => document.querySelector(".pi.hl")?.scrollIntoView({ block: "nearest" }));
}
export function palRun(i = S.ui.palette?.hl ?? 0) {
  const it = flat[i];
  if (!it) return;
  S.ui.palette = null;
  render();
  it.run();
}

export function Palette() {
  const pl = S.ui.palette;
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (pl && !S.ui.pop) ref.current?.focus();
  });
  if (!pl) return null;
  const groups = items();
  flat = groups.flatMap((g) => g.items);
  pl.hl = clamp(pl.hl, 0, Math.max(flat.length - 1, 0));
  let idx = 0;
  const ph = pl.mode === "search" ? "Search tasks, projects, documents, people, files, comments…" : pl.mode === "ws" ? "Find a workspace…" : "Type a command or search…";
  return (
    <>
      <div className="scrim" onClick={closePalette} style={{ zIndex: 89 }} />
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command menu">
        <div className="pal-in">
          <Ic n={pl.mode === "search" ? "search" : "command"} s={17} />
          {pl.mode !== "cmd" && (
            <span className="badge" style={{ flexShrink: 0 }}>
              {pl.mode === "search" ? "Search" : "Workspace"}
            </span>
          )}
          <input
            ref={ref}
            id="pal-in"
            value={pl.q}
            onChange={(e) => ((pl.q = e.target.value), (pl.hl = 0), render())}
            placeholder={ph}
            autoComplete="off"
            role="combobox"
            aria-expanded="true"
            aria-controls="pal-list"
            aria-activedescendant={`pi-${pl.hl}`}
          />
          <kbd>Esc</kbd>
        </div>
        {pl.mode === "search" && (
          <div className="pal-scope" role="tablist">
            {[
              ["all", "All", "layers"],
              ["tasks", "Tasks", "circle-check"],
              ["projects", "Projects", "folder"],
              ["documents", "Documents", "book-open"],
              ["people", "People", "users"],
              ["files", "Files", "paperclip"],
              ["comments", "Comments", "message-square"],
            ].map(([k, n, i]) => (
              <button key={k} role="tab" className={pl.scope === k ? "on" : ""} onClick={() => ((pl.scope = k!), (pl.hl = 0), render(), ref.current?.focus())}>
                <Ic n={i!} s={12} />
                {n}
              </button>
            ))}
          </div>
        )}
        <div className="pal-list" id="pal-list" role="listbox">
          {flat.length ? (
            groups.map((g, gi) => (
              <div key={gi} className="pal-group">
                {g.name && <div className="pal-sec">{g.name}</div>}
                {g.items.map((it) => {
                  const i = idx++;
                  return (
                    <div
                      key={i}
                      className={`pi ${i === pl.hl ? "hl" : ""}`}
                      id={`pi-${i}`}
                      role="option"
                      aria-selected={i === pl.hl}
                      onClick={() => palRun(i)}
                      onMouseMove={() => {
                        if (pl.hl !== i) {
                          pl.hl = i;
                          render();
                        }
                      }}
                    >
                      {it.html ?? <Ic n={it.icon || "circle"} s={15} />}
                      <span className="trunc">
                        <Hl text={it.name} q={pl.q.trim()} />
                      </span>
                      {it.sub && <span className="sub">{it.sub}</span>}
                      <span className="r">
                        {it.r && <span className="mono">{it.r}</span>}
                        {it.kbd?.split(" ").map((k, j) => (
                          <kbd key={j}>{k}</kbd>
                        ))}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))
          ) : (
            <div className="empty-state sm">
              <div className="glyph">
                <Ic n="search-x" s={18} />
              </div>
              <h2 className="es-h">No results found</h2>
              <p>Try a different keyword, or press Tab to search everything.</p>
            </div>
          )}
        </div>
        <div className="pal-f">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd>navigate
          </span>
          <span>
            <kbd>↵</kbd>select
          </span>
          {pl.mode === "cmd" ? (
            <span>
              <kbd>Tab</kbd>search mode
            </span>
          ) : (
            <span>
              <kbd>⌫</kbd>back to commands
            </span>
          )}
          <span className="sp" style={{ flex: 1 }} />
          <span>
            <Logo h={12} />
          </span>
        </div>
      </div>
    </>
  );
}
