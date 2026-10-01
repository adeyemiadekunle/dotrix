"use client";

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
import { Skeleton } from "@pmagent/ui/components/skeleton";
import {
  ActivityIcon,
  BellIcon,
  BotIcon,
  CircleCheckIcon,
  FolderKanbanIcon,
  LockIcon,
  ChartGanttIcon,
  HomeIcon,
  LayoutGridIcon,
  ListTodoIcon,
  MessageSquareIcon,
  PlusIcon,
  ScrollTextIcon,
  SearchIcon,
  SettingsIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { NavUser } from "@/components/nav-user";
import { ProjectTile } from "@/components/project-tile";
import { usePalette, useShortcutLabel } from "@/components/command-palette";
import { WorkspaceSwitcher } from "@/components/workspace-switcher";
import { canManageProjects } from "@/lib/labels";
import { useWorkspaceApprovals } from "@/lib/agent";
import { useWorkspaceIssues } from "@/lib/issues";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

// The open project's views, the same as its tabs. Timeline is shown but not built yet.
const PROJECT_VIEWS: { href: string; label: string; later?: boolean }[] = [
  { href: "overview", label: "Overview" },
  { href: "board", label: "Board" },
  { href: "list", label: "List" },
  { href: "table", label: "Table" },
  { href: "", label: "Timeline", later: true },
  { href: "files", label: "Files" },
  { href: "knowledge", label: "Knowledge" },
  { href: "activity", label: "Activity" },
];

/** A "Later" tag on what's planned but not built (Timeline). */
function Later() {
  return (
    <span className="ml-auto rounded-full bg-amber-100 px-1.5 text-[10px] font-semibold text-amber-800 group-data-[collapsible=icon]:hidden dark:bg-amber-950 dark:text-amber-300">
      Later
    </span>
  );
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
  const approvals = useWorkspaceApprovals(workspace?.id, Boolean(workspace && workspace.role !== "guest"));
  const waiting = approvals.data?.length ?? 0;
  const { setOpenMobile } = useSidebar();
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
                    <SidebarMenuButton asChild isActive={pathname === `${base}/chat`} tooltip="Chat">
                      <Link href={`${base}/chat${projectKey ? `?project=${projectKey}` : ""}`}>
                        <MessageSquareIcon />
                        <span>Chat</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/overview`} tooltip="Overview">
                      <Link href={`${base}/overview`}>
                        <LayoutGridIcon />
                        <span>Overview</span>
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
                    <SidebarMenuButton aria-disabled tooltip="Timeline (later)" className="text-muted-foreground cursor-default hover:bg-transparent">
                      <ChartGanttIcon />
                      <span>Timeline</span>
                      <Later />
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
                  {canManageProjects(workspace?.role) && (
                    <SidebarMenuItem>
                      <SidebarMenuButton asChild isActive={pathname.startsWith(`${base}/agents`)} tooltip="Agents">
                        <Link href={`${base}/agents`}>
                          <BotIcon />
                          <span>Agents</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )}
                  {canManageProjects(workspace?.role) && (
                    <SidebarMenuItem>
                      <SidebarMenuButton asChild isActive={pathname === `${base}/audit`} tooltip="Audit log">
                        <Link href={`${base}/audit`}>
                          <ScrollTextIcon />
                          <span>Audit log</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )}
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
              {projects.data?.map((project) => {
                const href = `${base}/p/${project.key}`; // opens its Overview
                const open = pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <SidebarMenuItem key={project.id}>
                    <SidebarMenuButton asChild isActive={open} tooltip={project.name}>
                      <Link href={href}>
                        <ProjectTile projectKey={project.key} className="-ml-0.5 group-data-[collapsible=icon]:ml-0 group-data-[collapsible=icon]:size-4 group-data-[collapsible=icon]:text-[9px]" />
                        <span className="flex-1 truncate">{project.name}</span>
                        {project.access === "restricted" && (
                          <LockIcon className="text-muted-foreground size-3.5! group-data-[collapsible=icon]:hidden" aria-label="Only people added" />
                        )}
                      </Link>
                    </SidebarMenuButton>
                    {open && (
                      <SidebarMenuSub aria-label={`${project.name} views`}>
                        {PROJECT_VIEWS.map((view) => (
                          <SidebarMenuSubItem key={view.label}>
                            {view.later ? (
                              <SidebarMenuSubButton aria-disabled className="text-muted-foreground cursor-default hover:bg-transparent">
                                <span>{view.label}</span>
                                <Later />
                              </SidebarMenuSubButton>
                            ) : (
                              <SidebarMenuSubButton asChild isActive={pathname === `${href}/${view.href}`}>
                                <Link href={`${href}/${view.href}`}>{view.label}</Link>
                              </SidebarMenuSubButton>
                            )}
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
            <SidebarMenuItem>
              <SidebarMenuButton asChild isActive={pathname === `${base}/settings`} tooltip="Settings">
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
