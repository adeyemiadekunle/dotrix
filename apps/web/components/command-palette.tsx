import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@dotrix/ui/components/dialog";
import { cn } from "@dotrix/ui/lib/utils";
import { useQuery } from "@tanstack/react-query";
import {
  ActivityIcon,
  ChartGanttIcon,
  BellIcon,
  BotIcon,
  CircleCheckIcon,
  FileTextIcon,
  FolderKanbanIcon,
  HomeIcon,
  LayoutGridIcon,
  ListTodoIcon,
  MessageSquareIcon,
  SearchIcon,
  SettingsIcon,
  UserIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { usePathname, useRouter } from "@/lib/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { StatusIcon } from "@/components/issues/meta";
import { ProjectTile } from "@/components/project-tile";
import { UserAvatar } from "@/components/user-avatar";
import { AGENTS } from "@/lib/agent";
import { api, unwrap } from "@/lib/api";
import { useMembers, useWorkspaceIssues } from "@/lib/issues";
import { can } from "@/lib/labels";
import { useMemberAvatarSrc, type Member } from "@/lib/profile";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

interface PaletteState {
  open: () => void;
}

const PaletteContext = createContext<PaletteState | null>(null);

/** "⌘K" on a Mac, "Ctrl K" elsewhere; known only in the browser, so it starts as "Ctrl K". */
export function useShortcutLabel(): string {
  const [label, setLabel] = useState("Ctrl K");
  useEffect(() => {
    if (/Mac|iPhone|iPad/.test(navigator.userAgent)) setLabel("⌘K");
  }, []);
  return label;
}

/** Opens the search palette (⌘K / Ctrl+K anywhere, or a Search button). */
export function usePalette(): PaletteState {
  const palette = useContext(PaletteContext);
  if (!palette) throw new Error("usePalette needs a PaletteProvider");
  return palette;
}

interface Result {
  id: string;
  group: string;
  label: ReactNode;
  hint?: string;
  icon: ReactNode;
  href: string;
}

const PAGES: { label: string; path: string; icon: LucideIcon }[] = [
  { label: "Home", path: "", icon: HomeIcon },
  { label: "Notifications", path: "/approvals", icon: BellIcon },
  { label: "My issues", path: "/my-issues", icon: CircleCheckIcon },
  { label: "Chat", path: "/chat", icon: MessageSquareIcon },
  { label: "Overview", path: "/overview", icon: LayoutGridIcon },
  { label: "Projects", path: "/projects", icon: FolderKanbanIcon },
  { label: "Tasks", path: "/tasks", icon: ListTodoIcon },
  { label: "Timeline", path: "/timeline", icon: ChartGanttIcon },
  { label: "Activity", path: "/activity", icon: ActivityIcon },
  { label: "Settings", path: "/settings", icon: SettingsIcon },
  { label: "Profile", path: "/settings/profile", icon: UserIcon },
  { label: "Members", path: "/settings/members", icon: UsersIcon },
];

function MemberPhoto({ member }: { member: Member }) {
  return <UserAvatar name={member.display_name} src={useMemberAvatarSrc(member)} className="size-5 text-[9px]" />;
}

/** Waits for typing to pause before searching documents on the server. */
function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function Palette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const { workspace } = useCurrentWorkspace();
  const canSee = Boolean(workspace && workspace.role !== "guest");
  const canChat = can(workspace, "agents:chat");
  const projects = useProjects(workspace?.id);
  const members = useMembers(open && canSee ? workspace?.id : undefined);
  // Chat started from inside a project is about that project.
  const projectKey = /\/p\/([^/]+)/.exec(pathname)?.[1];
  const issues = useWorkspaceIssues(open && canSee ? workspace?.id : undefined, {});
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const q = query.trim().toLowerCase();
  const debounced = useDebounced(q, 250);
  const documents = useQuery({
    queryKey: ["search", workspace?.id, debounced],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/search", {
          params: { path: { workspace_id: workspace!.id }, query: { q: debounced, source: "document", limit: 5 } },
        }),
      ),
    enabled: open && canSee && debounced.length >= 2,
  });
  const base = workspace ? `/w/${workspace.slug}` : "";

  const results = useMemo<Result[]>(() => {
    const out: Result[] = [];
    if (!workspace) return out;
    const matches = (text: string) => !q || text.toLowerCase().includes(q);
    const chatWith = (text: string) => `${base}/chat?${new URLSearchParams({ ...(projectKey ? { project: projectKey } : {}), q: text })}`;
    for (const issue of (issues.data ?? []).filter((i) => q && (matches(i.title) || matches(i.key))).slice(0, 6)) {
      out.push({
        id: `issue:${issue.key}`,
        group: "Issues",
        label: (
          <>
            <span className="text-muted-foreground w-16 shrink-0 font-mono text-xs">{issue.key}</span>
            <span className="truncate">{issue.title}</span>
          </>
        ),
        hint: issue.project_name,
        icon: <StatusIcon status={issue.status} />,
        href: `${base}/p/${issue.project_key}/board?issue=${issue.key}`,
      });
    }
    for (const hit of documents.data ?? []) {
      out.push({
        id: `doc:${hit.project_id}:${hit.ref}:${hit.heading}`,
        group: "Documents",
        label: (
          <span className="flex min-w-0 flex-col">
            <span className="truncate">
              <span className="font-mono text-xs">{hit.ref}</span>
              {hit.heading ? <span className="text-muted-foreground"> › {hit.heading}</span> : null}
            </span>
            <span className="text-muted-foreground truncate text-xs">{hit.snippet}</span>
          </span>
        ),
        hint: hit.project_name,
        icon: <FileTextIcon className="text-muted-foreground size-4" />,
        href: `${base}/p/${hit.project_key}/knowledge?file=${encodeURIComponent(hit.ref)}`,
      });
    }
    for (const project of (projects.data ?? []).filter((p) => matches(p.name) || matches(p.key)).slice(0, 6)) {
      out.push({
        id: `project:${project.key}`,
        group: "Projects",
        label: <span className="truncate">{project.name}</span>,
        hint: project.key,
        icon: <ProjectTile projectKey={project.key} className="size-4 text-[8px]" />,
        href: `${base}/p/${project.key}`,
      });
    }
    if (q && canChat) {
      for (const agent of AGENTS.filter((a) => a.id !== "auto" && (matches(a.name) || matches(a.id))).slice(0, 5)) {
        out.push({
          id: `agent:${agent.id}`,
          group: "Agents",
          label: <span className="truncate">{agent.name}</span>,
          hint: "Ask in Chat",
          icon: <BotIcon className="text-muted-foreground size-4" />,
          href: chatWith(`@${agent.id} `),
        });
      }
    }
    if (q) {
      const people = (members.data ?? []).filter((m) => matches(m.display_name) || matches(m.email) || (m.title ? matches(m.title) : false));
      for (const member of people.slice(0, 5)) {
        out.push({
          id: `person:${member.user_id}`,
          group: "People",
          label: <span className="truncate">{member.display_name}</span>,
          hint: member.title || "Their open issues",
          icon: <MemberPhoto member={member} />,
          href: `${base}/tasks?assignee=${member.user_id}`,
        });
      }
    }
    for (const page of PAGES.filter((p) => matches(p.label))) {
      out.push({
        id: `page:${page.path}`,
        group: "Go to",
        label: page.label,
        icon: <page.icon className="text-muted-foreground size-4" />,
        href: `${base}${page.path}`,
      });
    }
    if (q && canChat) {
      out.push({
        id: "chat",
        group: "Actions",
        label: <span className="truncate">Ask the agents in Chat: “{query.trim()}”</span>,
        icon: <MessageSquareIcon className="text-muted-foreground size-4" />,
        href: chatWith(query.trim()),
      });
    }
    return out;
  }, [workspace, issues.data, documents.data, projects.data, members.data, canChat, q, query, base, projectKey]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  function go(result: Result | undefined) {
    if (!result) return;
    onOpenChange(false);
    router.push(result.href);
  }

  let lastGroup = "";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[15%] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-xl" showCloseButton={false}>
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">Find issues, documents, projects, agents, people, and pages.</DialogDescription>
        <div className="flex items-center gap-2 border-b px-3">
          <SearchIcon className="text-muted-foreground size-4 shrink-0" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((i) => Math.min(i + 1, results.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                go(results[active]);
              }
            }}
            placeholder="Search issues, documents, people, agents…"
            aria-label="Search"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-results"
            aria-activedescendant={results[active] ? `palette-${active}` : undefined}
            className="h-12 flex-1 bg-transparent text-sm outline-none"
          />
          <kbd className="text-muted-foreground rounded border px-1.5 font-mono text-[10px]">Esc</kbd>
        </div>
        <ul id="palette-results" role="listbox" aria-label="Results" className="max-h-[60vh] overflow-y-auto p-1.5">
          {results.length === 0 && <li className="text-muted-foreground px-3 py-6 text-center text-sm">Nothing matches.</li>}
          {results.map((result, index) => {
            const heading = result.group !== lastGroup;
            lastGroup = result.group;
            return (
              <li key={result.id} role="presentation">
                {heading && <p className="text-muted-foreground px-2 pt-2 pb-1 text-[11px] font-semibold tracking-wider uppercase">{result.group}</p>}
                <div
                  id={`palette-${index}`}
                  role="option"
                  aria-selected={index === active}
                  onMouseMove={() => setActive(index)}
                  onClick={() => go(result)}
                  className={cn("flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm", index === active && "bg-muted")}
                >
                  {result.icon}
                  <span className="flex min-w-0 flex-1 items-center gap-2">{result.label}</span>
                  {result.hint && <span className="text-muted-foreground shrink-0 text-xs">{result.hint}</span>}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="text-muted-foreground flex gap-4 border-t px-3 py-2 text-[11px]">
          <span>↑ ↓ to move</span>
          <span>↵ to open</span>
          <span className="ml-auto">Documents are searched by meaning and keywords</span>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** The search palette for the signed-in app: ⌘K / Ctrl+K opens it from anywhere. */
export function PaletteProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const show = useCallback(() => setOpen(true), []);
  return (
    <PaletteContext value={{ open: show }}>
      {children}
      {open && <Palette open={open} onOpenChange={setOpen} />}
    </PaletteContext>
  );
}
