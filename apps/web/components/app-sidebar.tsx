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
import {
  BellIcon,
  BotIcon,
  CircleCheckIcon,
  FolderKanbanIcon,
  HomeIcon,
  PlusIcon,
  ScrollTextIcon,
  SettingsIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { NavUser } from "@/components/nav-user";
import { ProjectTile } from "@/components/project-tile";
import { WorkspaceSwitcher } from "@/components/workspace-switcher";
import { canManageProjects } from "@/lib/labels";
import { useWorkspaceApprovals } from "@/lib/agent";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

// The open project's views, the same as its tabs (Chat and Briefing aside, which move to the
// workspace Chat).
const PROJECT_VIEWS = [
  { href: "overview", label: "Overview" },
  { href: "board", label: "Board" },
  { href: "list", label: "List" },
  { href: "table", label: "Table" },
  { href: "files", label: "Files" },
  { href: "knowledge", label: "Knowledge" },
  { href: "activity", label: "Activity" },
];

/** Placeholder rows while the workspace loads: links without it would point outside it. */
function NavSkeleton({ rows }: { rows: number }) {
  return Array.from({ length: rows }, (_, i) => (
    <SidebarMenuItem key={i}>
      <SidebarMenuSkeleton showIcon />
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
  // On phones the sidebar is a sheet over the page: close it once you've picked somewhere to go.
  useEffect(() => setOpenMobile(false), [pathname, setOpenMobile]);
  const base = workspace ? `/w/${workspace.slug}` : "";

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
                  </SidebarMenuItem>
                </>
              ) : (
                <NavSkeleton rows={3} />
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
                    <SidebarMenuButton asChild isActive={pathname === `${base}/projects`} tooltip="Projects">
                      <Link href={`${base}/projects`}>
                        <FolderKanbanIcon />
                        <span>Projects</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton asChild isActive={pathname === `${base}/settings`} tooltip="Members and settings">
                      <Link href={`${base}/settings`}>
                        <SettingsIcon />
                        <span>Members and settings</span>
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
                <NavSkeleton rows={2} />
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
                        <span className="text-muted-foreground font-mono text-[11px] group-data-[collapsible=icon]:hidden">
                          {project.key}
                        </span>
                      </Link>
                    </SidebarMenuButton>
                    {open && (
                      <SidebarMenuSub aria-label={`${project.name} views`}>
                        {PROJECT_VIEWS.map((view) => (
                          <SidebarMenuSubItem key={view.href}>
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
        <NavUser />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
