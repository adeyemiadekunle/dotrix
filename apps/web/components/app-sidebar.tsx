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
  SidebarRail,
  useSidebar,
} from "@pmagent/ui/components/sidebar";
import { FolderKanbanIcon, PlusIcon, ShieldCheckIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { NavUser } from "@/components/nav-user";
import { WorkspaceSwitcher } from "@/components/workspace-switcher";
import { canManageProjects } from "@/lib/labels";
import { useWorkspaceApprovals } from "@/lib/agent";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

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
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname === base} tooltip="Projects">
                  <Link href={base || "/"}>
                    <FolderKanbanIcon />
                    <span>Projects</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname === `${base}/approvals`} tooltip="Approvals">
                  <Link href={`${base}/approvals`}>
                    <ShieldCheckIcon />
                    <span>Approvals</span>
                  </Link>
                </SidebarMenuButton>
                {waiting > 0 && (
                  <SidebarMenuBadge className="bg-warning text-warning-foreground dark:text-background rounded-full px-1.5">
                    {waiting}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>
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
                const href = `${base}/p/${project.key}`; // opens the board
                return (
                  <SidebarMenuItem key={project.id}>
                    <SidebarMenuButton asChild isActive={pathname.startsWith(href)} tooltip={project.name}>
                      <Link href={href}>
                        <span className="text-muted-foreground w-4 shrink-0 text-center font-mono text-[10px] group-data-[collapsible=icon]:w-full">
                          {project.key.slice(0, 3)}
                        </span>
                        <span className="truncate">{project.name}</span>
                      </Link>
                    </SidebarMenuButton>
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
