import { CommandPalette, CommandPaletteInput, TabList, Tab } from "@dotrix/ui/astryx";
// Command palette: commands, then search over
// everything (Tab switches), and the workspace switcher. dotrix adds Chat, the agents (Chat opens
// with that agent picked), documents, and "Ask the agents" with what you typed.
import { useMemo, type CSSProperties, type ReactNode } from "react";

import { openTask, setPref, toggleSide } from "../core/actions";
import { PSTAT } from "../core/constants";
import { Ic, WsLogo } from "../core/icons";
import { allowed, canInvite } from "../core/can";
import { personal, tasksLabel } from "../core/features";
import { invite, newProject, newTask, openModal, shortcuts, signOut, switchWs } from "../core/more";
import { go } from "../core/nav";
import { effectiveDark } from "../core/theme";
import { MOD } from "../core/utils";
import { D, S, allTasks, pColor, proj, render, save, task } from "../data/store";
import { searchAll } from "../screens/Search";
import { goTasks } from "../screens/Home";
import { setPaletteOpener } from "../shell/Shell";
import { sortTasks } from "../shell/viewEngine";
import { Av, FT, StIcon } from "../ui/helpers";
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

// Commands only some people may run: shown to them alone.
const NEEDS: Record<string, () => boolean> = {
  "c-proj": () => allowed("projects:manage"),
  "c-inv": canInvite,
  "c-mem": () => !personal(),
  "c-ws": () => D().workspaces.length > 1,
  "c-agents": () => allowed("workspace:manage"),
};

function commands(): (Item & { id: string })[] {
  return (
    [
      { id: "c-task", name: "Create task", icon: "plus", kbd: "N", run: () => newTask() },
      { id: "c-proj", name: "Create project", icon: "folder-plus", kbd: "P", run: newProject },
      { id: "c-chat", name: "Ask the agents in Chat", icon: "message-square", run: () => go("chat", {}, { search: "new=1" }) },
      { id: "c-search", name: "Search workspace", icon: "search", kbd: "/", run: () => openPalette("search") },
      { id: "c-home", name: "Go to Home", icon: "house", kbd: "G H", run: () => go("home") },
      { id: "c-inbox", name: "Go to Inbox", icon: "inbox", kbd: "G I", run: () => go("inbox") },
      { id: "c-my", name: `Go to ${tasksLabel()}`, icon: "circle-check", kbd: "G T", run: () => go("mytasks") },
      { id: "c-chatgo", name: "Go to Chat", icon: "message-square", kbd: "G A", run: () => go("chat") },
      { id: "c-codinggo", name: "Go to Codes", icon: "code", kbd: "G C", run: () => go("codes") },
      { id: "c-coding", name: "Start a session with Kai", icon: "code", run: () => go("codes", {}, { search: "new=1" }) },
      { id: "c-projs", name: "Go to Projects", icon: "folder-kanban", kbd: "G P", run: () => go("projects") },
      { id: "c-mem", name: "Members settings", icon: "users", run: () => go("settings", { sec: "members" }) },
      { id: "c-set", name: "Open settings", icon: "settings", kbd: "G S", run: () => go("settings") },
      { id: "c-agents", name: "Agents settings", icon: "bot", run: () => go("settings", { sec: "agents" }) },
      { id: "c-app", name: "Preferences settings", icon: "palette", run: () => go("settings", { sec: "preferences" }) },
      { id: "c-ws", name: "Switch workspace…", icon: "arrow-left-right", run: () => ((S.ui.palette = { q: "", mode: "ws", scope: "all", hl: 0 }), render()) },
      {
        id: "c-dark",
        name: effectiveDark() ? "Switch to light mode" : "Switch to dark mode",
        icon: effectiveDark() ? "sun" : "moon",
        kbd: MOD + " ⇧ L",
        run: toggleDark,
      },
      { id: "c-inv", name: "Invite member", icon: "user-plus", run: invite },
      { id: "c-side", name: "Toggle sidebar", icon: "panel-left", kbd: "[", run: toggleSide },
      { id: "c-keys", name: "Keyboard shortcuts", icon: "keyboard", kbd: "?", run: shortcuts },
      { id: "c-out", name: "Sign out", icon: "log-out", run: signOut },
    ] as (Item & { id: string })[]
  ).filter((c) => NEEDS[c.id]?.() ?? true);
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
      groups.push({
        name: "Recent tasks",
        items: recent.map((t) => ({ html: <StIcon st={t.status} />, name: t.title, sub: proj(t.project)?.name, r: t.key, run: () => openTask(t.id) })),
      });
      groups.push({ name: "Navigation", items: cmds.filter((c) => c.name.startsWith("Go to")) });
      return groups;
    }
    if (cmds.length) groups.push({ name: "Commands", items: cmds.slice(0, 5) });
    const ags = D().agents.filter((a) => a.name.toLowerCase().includes(ql) || a.handle.includes(ql) || "agent".startsWith(ql));
    if (ags.length)
      groups.push({
        name: "Agents",
        items: ags.map((a) => ({
          html: agentIcon(a.c),
          name: a.name,
          sub: `${a.role} · ${a.desc}`,
          run: () => go("chat", {}, { search: `new=1&agent=${a.handle}` }),
        })),
      });
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
        { icon: "shield-check", name: "Changes waiting for my approval", run: () => go("inbox", {}, { search: "tab=needs" }) },
        { icon: "paperclip", name: "Files in Website Redesign", run: () => go("project", { id: "WEB", tab: "files" }) },
      ],
    });
    return groups;
  }
  if (!q) return groups;
  if (sc === "all" || sc === "tasks")
    groups.push({
      name: "Tasks",
      items: r.tasks
        .slice(0, lim)
        .map((t) => ({ html: <StIcon st={t.status} />, name: t.title, sub: proj(t.project)?.name, r: t.key, run: () => openTask(t.id) })),
    });
  if (sc === "all" || sc === "projects")
    groups.push({
      name: "Projects",
      items: r.projects.slice(0, lim).map((p) => ({
        html: <span className="pdot" style={{ "--c": pColor(p) } as CSSProperties} />,
        name: p.name,
        sub: PSTAT[p.status].name,
        run: () => go("project", { id: p.key }),
      })),
    });
  if (sc === "all" || sc === "documents")
    groups.push({
      name: "Documents",
      items: r.documents.slice(0, lim).map((f) => ({
        icon: "book-open",
        name: f.path,
        sub: proj(f.project)?.name,
        run: () => go("project", { id: proj(f.project)!.key, tab: "knowledge" }),
      })),
    });
  if (sc === "all" || sc === "people")
    groups.push({
      name: "People",
      items: r.people
        .slice(0, lim)
        .map((m) => ({ html: <Av id={m.id} cls="sm" tip={false} />, name: m.name, sub: m.title, run: () => go("member", { id: m.id }) })),
    });
  if (sc === "all" || sc === "files")
    groups.push({
      name: "Files",
      items: r.files.slice(0, lim).map((f) => ({
        icon: (FT[f.type] || FT.other!).i,
        name: f.name,
        sub: proj(f.project)?.name,
        r: f.size,
        run: () => openModal({ type: "filePreview", file: f, tid: f.task }),
      })),
    });
  if (sc === "all" || sc === "comments")
    groups.push({
      name: "Comments",
      items: r.comments
        .slice(0, lim)
        .map((c) => ({ html: <Av id={c.by} cls="sm" tip={false} />, name: c.text, sub: "on " + task(c.task)?.title, run: () => openTask(c.task) })),
    });
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

export function Palette() {
  const pl = S.ui.palette;
  const mode = pl?.mode;
  const scope = pl?.scope;
  const source = useMemo(() => {
    const search = (query: string) => {
      if (!S.ui.palette || S.ui.palette.mode !== mode || S.ui.palette.scope !== scope) return [];
      S.ui.palette.q = query;
      return items().flatMap((group, gi) =>
        group.items.map((item, i) => ({
          id: `${gi}-${i}`,
          label: item.name,
          auxiliaryData: { ...item, group: group.name },
        })),
      );
    };
    return { search, bootstrap: () => search(S.ui.palette?.q ?? "") };
  }, [mode, scope]);
  if (!pl) return null;
  const placeholder =
    pl.mode === "search" ? "Search tasks, projects, documents, people, files, comments…" : pl.mode === "ws" ? "Find a workspace…" : "Type a command or search…";
  return (
    <CommandPalette
      key={`${pl.mode}:${pl.scope}`}
      isOpen
      label="Command menu"
      width={640}
      maxHeight="80dvh"
      onOpenChange={(open) => {
        if (!open) closePalette();
      }}
      searchSource={source}
      onValueChange={(id) => {
        const action = source.bootstrap().find((item) => item.id === id)?.auxiliaryData.run;
        queueMicrotask(() => action?.());
      }}
      input={
        <>
          <div
            onKeyDownCapture={(e) => {
              if (e.key === "Tab" && pl.mode === "cmd") {
                e.preventDefault();
                pl.mode = "search";
                render();
              }
              if (e.key === "Backspace" && !pl.q && pl.mode !== "cmd") {
                e.preventDefault();
                pl.mode = "cmd";
                render();
              }
            }}
          >
            <CommandPaletteInput label="Search commands" placeholder={placeholder} />
          </div>
          {pl.mode === "search" && (
            <TabList
              aria-label="Search scope"
              value={pl.scope}
              onChange={(scope) => {
                pl.scope = scope;
                render();
              }}
              size="sm"
            >
              {[
                ["all", "All"],
                ["tasks", "Tasks"],
                ["projects", "Projects"],
                ["documents", "Documents"],
                ["people", "People"],
                ["files", "Files"],
                ["comments", "Comments"],
              ].map(([value, label]) => (
                <Tab key={value} value={value!} label={label!} />
              ))}
            </TabList>
          )}
        </>
      }
      emptySearchText="No results found. Try a different keyword."
      renderItem={(item) => (
        <>
          <span>{item.auxiliaryData.html ?? <Ic n={item.auxiliaryData.icon ?? "circle"} s={16} />}</span>
          <span className="grow">{item.label}</span>
          {item.auxiliaryData.sub && <span className="muted">{item.auxiliaryData.sub}</span>}
          <span className="mono muted">{item.auxiliaryData.kbd ?? item.auxiliaryData.r}</span>
        </>
      )}
      aria-description={placeholder}
    />
  );
}
