import type { Schemas } from "@dotrix/api-client";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@dotrix/ui/components/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar } from "@dotrix/ui/components/sidebar";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { CheckIcon, ChevronsUpDownIcon, PlusIcon } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useState } from "react";

import { CreateOrganizationDialog } from "@/components/create-organization-dialog";
import { ROLE_LABELS, WORKSPACE_KIND_LABELS, initials } from "@/lib/labels";
import { useCurrentWorkspace, useWorkspaces } from "@/lib/queries";

export function WorkspaceSwitcher() {
  const router = useRouter();
  const { isMobile } = useSidebar();
  const workspaces = useWorkspaces();
  const { shown: current } = useCurrentWorkspace();
  const [creating, setCreating] = useState(false);

  if (!current) return <Skeleton className="h-12 w-full" />;

  const all = workspaces.data ?? [];
  const groups: [string, Schemas["WorkspaceWithRole"][]][] = [
    ["Personal", all.filter((w) => w.kind === "personal")],
    ["Organisations", all.filter((w) => w.kind === "organization")],
  ];

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <span className="bg-brand text-brand-foreground flex aspect-square size-8 items-center justify-center rounded-lg text-xs font-semibold">
                {initials(current.name)}
              </span>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{current.name}</span>
                <span className="text-muted-foreground truncate text-xs">
                  {WORKSPACE_KIND_LABELS[current.kind]} · {ROLE_LABELS[current.role]}
                </span>
              </div>
              <ChevronsUpDownIcon className="ml-auto" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-64 rounded-lg"
            align="start"
            side={isMobile ? "bottom" : "right"}
            sideOffset={4}
          >
            {groups
              .filter(([, items]) => items.length > 0)
              .map(([label, items]) => (
                <DropdownMenuGroup key={label}>
                  <DropdownMenuLabel className="text-muted-foreground text-xs">{label}</DropdownMenuLabel>
                  {items.map((w) => (
                    <DropdownMenuItem key={w.id} onSelect={() => router.push(`/w/${w.slug}`)} className="gap-2 p-2">
                      <span className="flex size-6 items-center justify-center rounded-md border text-[10px] font-medium">
                        {initials(w.name)}
                      </span>
                      <span className="flex-1 truncate">{w.name}</span>
                      {w.id === current.id && <CheckIcon className="size-4" />}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuGroup>
              ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem className="gap-2 p-2" onSelect={() => setCreating(true)}>
              <span className="flex size-6 items-center justify-center rounded-md border">
                <PlusIcon className="size-4" />
              </span>
              <span className="grid">
                <span className="text-muted-foreground font-medium">Create organisation</span>
                <span className="text-muted-foreground text-xs">For a team: invite people, share projects</span>
              </span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <CreateOrganizationDialog open={creating} onOpenChange={setCreating} />
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
