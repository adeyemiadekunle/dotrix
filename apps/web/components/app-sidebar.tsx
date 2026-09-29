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
import {
  BotIcon,
  BuildingIcon,
  FolderKanbanIcon,
  PlusIcon,
  ScrollTextIcon,
  SettingsIcon,
  ShieldCheckIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { NavUser } from "@/components/nav-user";
import { ProjectTile } from "@/components/project-tile";
import { CreateOrgDialog } from "@/components/orgs/create-org-dialog";
import { WorkspaceSwitcher } from "@/components/workspace-switcher";
import { canManageProjects } from "@/lib/labels";
import { useWorkspaceApprovals } from "@/lib/agent";
import { useOrgs } from "@/lib/orgs";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

export function AppSidebar() {
  const pathname = usePathname();
  const { shown: workspace } = useCurrentWorkspace();
  const projects = useProjects(workspace?.id);
  const approvals = useWorkspaceApprovals(workspace?.id, Boolean(workspace && workspace.role !== "guest"));
  const waiting = approvals.data?.length ?? 0;
  const orgs = useOrgs();
  const [creatingOrg, setCreatingOrg] = useState(false);
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
                  <SidebarMenuBadge className="bg-primary text-primary-foreground peer-hover/menu-button:text-primary-foreground peer-data-[active=true]/menu-button:text-primary-foreground rounded-full px-1.5">
                    {waiting}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={pathname.startsWith(`${base}/agents`)} tooltip="Agents">
                  <Link href={`${base}/agents`}>
                    <BotIcon />
                    <span>Agents</span>
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
                  <SidebarMenuButton asChild isActive={pathname === `${base}/audit`} tooltip="Audit log">
                    <Link href={`${base}/audit`}>
                      <ScrollTextIcon />
                      <span>Audit log</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
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
                const href = `${base}/p/${project.key}`; // opens the board
                return (
                  <SidebarMenuItem key={project.id}>
                    <SidebarMenuButton asChild isActive={pathname.startsWith(href)} tooltip={project.name}>
                      <Link href={href}>
                        <ProjectTile projectKey={project.key} className="-ml-0.5 group-data-[collapsible=icon]:ml-0 group-data-[collapsible=icon]:size-4 group-data-[collapsible=icon]:text-[9px]" />
                        <span className="flex-1 truncate">{project.name}</span>
                        <span className="text-muted-foreground font-mono text-[11px] group-data-[collapsible=icon]:hidden">
                          {project.key}
                        </span>
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
        {(orgs.data?.length ?? 0) > 0 && (
          <SidebarGroup>
            <SidebarGroupLabel>Organisations</SidebarGroupLabel>
            <SidebarGroupAction title="New organisation" onClick={() => setCreatingOrg(true)}>
              <PlusIcon />
              <span className="sr-only">New organisation</span>
            </SidebarGroupAction>
            <SidebarGroupContent>
              <SidebarMenu>
                {orgs.data?.map((o) => (
                  <SidebarMenuItem key={o.id}>
                    <SidebarMenuButton asChild isActive={pathname.startsWith(`/o/${o.slug}`)} tooltip={o.name}>
                      <Link href={`/o/${o.slug}`}>
                        <BuildingIcon />
                        <span className="truncate">{o.name}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
      <CreateOrgDialog open={creatingOrg} onOpenChange={setCreatingOrg} />
      <SidebarFooter>
        <NavUser />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
