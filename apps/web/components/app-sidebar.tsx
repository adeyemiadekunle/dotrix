import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  useSidebar,
} from "@pmagent/ui/components/sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import {
  ActivityIcon,
  BellIcon,
  ChevronRightIcon,
  CircleCheckIcon,
  CircleHelpIcon,
  EllipsisIcon,
  KeyboardIcon,
  LinkIcon,
  TerminalIcon,
  FolderKanbanIcon,
  LockIcon,
  StarIcon,
  ChartGanttIcon,
  HomeIcon,
  LayoutGridIcon,
  ListTodoIcon,
  MessageSquareIcon,
  PlusIcon,
  SearchIcon,
  SettingsIcon,
} from "lucide-react";
import { Link, usePathname } from "@/lib/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { NavUser } from "@/components/nav-user";
import { ProjectTile } from "@/components/project-tile";
import { ConnectCliDialog, KeyboardShortcutsDialog } from "@/components/user-menu-dialogs";
import { usePalette, useShortcutLabel } from "@/components/command-palette";
import { WorkspaceSwitcher } from "@/components/workspace-switcher";
import { canManageProjects } from "@/lib/labels";
import { useWorkspaceIssues } from "@/lib/issues";
import { useNotificationCounts } from "@/lib/notifications";
import { projectDot } from "@/lib/project-look";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";
import { starredFirst, useStarredProjects, useToggleStar } from "@/lib/stars";

// The open project's views, the same as its tabs.
const PROJECT_VIEWS: { href: string; label: string }[] = [
  { href: "overview", label: "Overview" },
  { href: "board", label: "Board" },
  { href: "list", label: "List" },
  { href: "table", label: "Table" },
  { href: "timeline", label: "Timeline" },
  { href: "files", label: "Files" },
  { href: "knowledge", label: "Knowledge" },
  { href: "activity", label: "Activity" },
];

const EXPANDED_KEY = "pmagent:sidebar-projects";

/**
 * Which projects show their views in the sidebar: the one you're in until you fold it, and any
 * other you open. Remembered in this browser (a convenience: it falls back to the defaults).
 */
function useExpandedProjects(): [Record<string, boolean>, (projectId: string, open: boolean) => void] {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  useEffect(() => {
    try {
      setExpanded(JSON.parse(localStorage.getItem(EXPANDED_KEY) ?? "{}"));
    } catch {
      // storage blocked or garbled: the defaults
    }
  }, []);
  function set(projectId: string, open: boolean) {
    setExpanded((current) => {
      const next = { ...current, [projectId]: open };
      try {
        localStorage.setItem(EXPANDED_KEY, JSON.stringify(next));
      } catch {
        // only a convenience
      }
      return next;
    });
  }
  return [expanded, set];
}

/**
 * Placeholder rows while the workspace loads: links without it would point outside it. Fixed
 * widths, since these render on the server too (SidebarMenuSkeleton's random width wouldn't match).
 */
function NavSkeleton({ rows }: { rows: number }) {
  return ["70%", "55%", "62%", "48%", "66%", "58%"].slice(0, rows).map((width) => (
    <SidebarMenuItem key={width}>
      <div className="flex h-8 items-center gap-2 rounded-md px-2">
        <Skeleton className="size-4 rounded-md" />
        <Skeleton className="h-4 flex-1" style={{ maxWidth: width }} />
      </div>
    </SidebarMenuItem>
  ));
}

export function AppSidebar() {
  const pathname = usePathname();
  const { shown: workspace } = useCurrentWorkspace();
  const projects = useProjects(workspace?.id);
  const starred = useStarredProjects(workspace?.id);
  const counts = useNotificationCounts(workspace?.id);
  const waiting = counts.data?.unread ?? 0;
  const { setOpenMobile } = useSidebar();
  const [expanded, setExpanded] = useExpandedProjects();
  const palette = usePalette();
  const shortcut = useShortcutLabel();
  const canSee = Boolean(workspace && workspace.role !== "guest");
  const mine = useWorkspaceIssues(canSee ? workspace?.id : undefined, { assignee: "me" });
  const myOpen = (mine.data ?? []).filter((i) => i.status !== "done").length;
  // On phones the sidebar is a sheet over the page: close it once you've picked somewhere to go.
  useEffect(() => setOpenMobile(false), [pathname, setOpenMobile]);
  const base = workspace ? `/w/${workspace.slug}` : "";
  // From inside a project, Chat opens about that project.
  const projectKey = pathname.match(/^\/w\/[^/]+\/p\/([^/]+)/)?.[1];

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <WorkspaceSwitcher />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {workspace ? (
                <>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === base} tooltip="Home">
                      <Link href={base || "/"}>
                        <HomeIcon />
                        <span>Home</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/approvals`} tooltip="Notifications">
                      <Link href={`${base}/approvals`}>
                        <BellIcon />
                        <span>Notifications</span>
                      </Link>
                    </SidebarMenuButton>
                    {waiting > 0 && (
                      <SidebarMenuBadge className="bg-primary text-primary-foreground peer-hover/menu-button:text-primary-foreground peer-data-[active=true]/menu-button:text-primary-foreground rounded-full px-1.5">
                        {waiting}
                      </SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/my-issues`} tooltip="My issues">
                      <Link href={`${base}/my-issues`}>
                        <CircleCheckIcon />
                        <span>My issues</span>
                      </Link>
                    </SidebarMenuButton>
                    {myOpen > 0 && <SidebarMenuBadge className="text-muted-foreground">{myOpen}</SidebarMenuBadge>}
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton onClick={palette.open} tooltip={`Search (${shortcut})`}>
                      <SearchIcon />
                      <span>Search</span>
                      <kbd className="text-muted-foreground ml-auto rounded border px-1 font-mono text-[10px] group-data-[collapsible=icon]:hidden">
                        {shortcut}
                      </kbd>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </>
              ) : (
                <NavSkeleton rows={4} />
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {workspace ? (
                <>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/overview`} tooltip="Overview">
                      <Link href={`${base}/overview`}>
                        <LayoutGridIcon />
                        <span>Overview</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/chat`} tooltip="Chat">
                      <Link href={`${base}/chat${projectKey ? `?project=${projectKey}` : ""}`}>
                        <MessageSquareIcon />
                        <span>Chat</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/projects`} tooltip="Projects">
                      <Link href={`${base}/projects`}>
                        <FolderKanbanIcon />
                        <span>Projects</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/tasks`} tooltip="Tasks">
                      <Link href={`${base}/tasks`}>
                        <ListTodoIcon />
                        <span>Tasks</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/timeline`} tooltip="Timeline">
                      <Link href={`${base}/timeline`}>
                        <ChartGanttIcon />
                        <span>Timeline</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/activity`} tooltip="Activity">
                      <Link href={`${base}/activity`}>
                        <ActivityIcon />
                        <span>Activity</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </>
              ) : (
                <NavSkeleton rows={6} />
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Projects</SidebarGroupLabel>
          {canManageProjects(workspace?.role) && (
            <SidebarGroupAction title="New project" asChild>
              <Link href={`${base}/projects/new`}>
                <PlusIcon />
                <span className="sr-only">New project</span>
              </Link>
            </SidebarGroupAction>
          )}
          <SidebarGroupContent>
            <SidebarMenu>
              {projects.isLoading &&
                Array.from({ length: 3 }, (_, i) => (
                  <SidebarMenuItem key={i}>
                    <SidebarMenuSkeleton />
                  </SidebarMenuItem>
                ))}
              {starredFirst(projects.data ?? [], starred.data).map((project) => {
                const href = `${base}/p/${project.key}`; // opens its Overview
                const open = pathname === href || pathname.startsWith(`${href}/`);
                const showViews = expanded[project.id] ?? open;
                const dot = projectDot(project);
                return (
                  <SidebarMenuItem key={project.id}>
                    <SidebarMenuButton asChild isActive={open} tooltip={project.name}>
                      <Link href={href}>
                        <ProjectTile projectKey={project.key} className="-ml-0.5 group-data-[collapsible=icon]:ml-0 group-data-[collapsible=icon]:size-4 group-data-[collapsible=icon]:text-[9px]" />
                        <span className="flex-1 truncate">{project.name}</span>
                        {starred.data?.includes(project.id) && (
                          <StarIcon
                            className="size-3.5! fill-warning text-warning group-data-[collapsible=icon]:hidden"
                            aria-label="Starred"
                          />
                        )}
                        {project.access === "restricted" && (
                          <LockIcon className="text-muted-foreground size-3.5! group-data-[collapsible=icon]:hidden" aria-label="Only people added" />
                        )}
                        <span
                          className={cn(
                            "mr-5 size-1.5 shrink-0 rounded-full group-hover/menu-item:opacity-0 group-data-[collapsible=icon]:hidden",
                            dot.dot,
                          )}
                          title={dot.label}
                          aria-label={dot.label}
                        />
                      </Link>
                    </SidebarMenuButton>
                    <ProjectMenu
                      project={project}
                      href={href}
                      starred={Boolean(starred.data?.includes(project.id))}
                      canManage={canManageProjects(workspace?.role)}
                    />
                    <SidebarMenuAction
                      onClick={() => setExpanded(project.id, !showViews)}
                      aria-expanded={showViews}
                      aria-label={`${showViews ? "Hide" : "Show"} ${project.name} views`}
                      title={showViews ? "Hide views" : "Show views"}
                    >
                      <ChevronRightIcon className={cn("transition-transform", showViews && "rotate-90")} />
                    </SidebarMenuAction>
                    {showViews && (
                      <SidebarMenuSub aria-label={`${project.name} views`}>
                        {PROJECT_VIEWS.map((view) => (
                          <SidebarMenuSubItem key={view.label}>
                            <SidebarMenuSubButton asChild isActive={pathname === `${href}/${view.href}`}>
                              <Link href={`${href}/${view.href}`}>{view.label}</Link>
                            </SidebarMenuSubButton>
                          </SidebarMenuSubItem>
                        ))}
                      </SidebarMenuSub>
                    )}
                  </SidebarMenuItem>
                );
              })}
              {projects.data?.length === 0 && (
                <p className="text-muted-foreground px-2 py-1 text-xs group-data-[collapsible=icon]:hidden">
                  No projects yet.
                </p>
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        {workspace && (
          <SidebarMenu>
            <HelpMenu workspaceSlug={workspace.slug} />
            <SidebarMenuItem>
              <SidebarMenuButton asChild isActive={pathname.startsWith(`${base}/settings`)} tooltip="Settings">
                <Link href={`${base}/settings`}>
                  <SettingsIcon />
                  <span>Settings</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        )}
        <NavUser />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

/** A project's menu in the sidebar (⋯ on hover): open it, star it, copy its link, its settings. */
function ProjectMenu({
  project,
  href,
  starred,
  canManage,
}: {
  project: { id: string; name: string; workspace_id: string };
  href: string;
  starred: boolean;
  canManage: boolean;
}) {
  const toggleStar = useToggleStar(project.workspace_id);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuAction showOnHover className="right-7" aria-label={`${project.name} options`} title="Options">
          <EllipsisIcon />
        </SidebarMenuAction>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="start" className="w-48">
        <DropdownMenuItem asChild>
          <Link href={`${href}/overview`}>
            <FolderKanbanIcon />
            Open
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => toggleStar.mutate({ projectId: project.id, starred: !starred })}>
          <StarIcon />
          {starred ? "Unstar" : "Star"}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() =>
            void navigator.clipboard
              .writeText(`${location.origin}${href}/overview`)
              .then(() => toast.success("Link copied"))
              .catch(() => toast.error("Couldn't copy the link"))
          }
        >
          <LinkIcon />
          Copy link
        </DropdownMenuItem>
        {canManage && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href={`${href}/settings`}>
                <SettingsIcon />
                Project settings
              </Link>
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Help and resources: the keyboard shortcuts, and connecting the CLI. */
function HelpMenu({ workspaceSlug }: { workspaceSlug: string }) {
  const [dialog, setDialog] = useState<"shortcuts" | "cli" | null>(null);
  return (
    <SidebarMenuItem>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <SidebarMenuButton tooltip="Help and resources">
            <CircleHelpIcon />
            <span>Help and resources</span>
          </SidebarMenuButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="end" className="w-56">
          <DropdownMenuItem onSelect={() => setDialog("shortcuts")}>
            <KeyboardIcon />
            Keyboard shortcuts
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setDialog("cli")}>
            <TerminalIcon />
            Connect the CLI
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <KeyboardShortcutsDialog open={dialog === "shortcuts"} onOpenChange={(open) => !open && setDialog(null)} />
      <ConnectCliDialog
        open={dialog === "cli"}
        onOpenChange={(open) => !open && setDialog(null)}
        workspaceSlug={workspaceSlug}
      />
    </SidebarMenuItem>
  );
}
