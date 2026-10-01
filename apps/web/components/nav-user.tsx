"use client";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar } from "@pmagent/ui/components/sidebar";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { ChevronsUpDownIcon, LogOutIcon, MonitorIcon, MoonIcon, SettingsIcon, SunIcon, UserIcon } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";

import { UserAvatar } from "@/components/user-avatar";
import { authPost } from "@/lib/api";
import { myAvatarSrc } from "@/lib/profile";
import { useCurrentWorkspace, useMe } from "@/lib/queries";

async function signOut() {
  await authPost("logout").catch(() => undefined);
  window.location.assign("/login");
}

export function NavUser() {
  const { isMobile } = useSidebar();
  const me = useMe();
  const { workspace } = useCurrentWorkspace();
  const { theme, setTheme } = useTheme();
  if (!me.data) return <Skeleton className="h-12 w-full" />;
  const user = me.data;

  const who = (
    <>
      <UserAvatar name={user.display_name} src={myAvatarSrc(user)} className="rounded-lg *:rounded-lg" />
      <div className="grid flex-1 text-left text-sm leading-tight">
        <span className="truncate font-medium">{user.display_name}</span>
        <span className="text-muted-foreground truncate text-xs">{user.email}</span>
      </div>
    </>
  );

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              {who}
              <ChevronsUpDownIcon className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuLabel className="p-0 font-normal">
              <div className="flex items-center gap-2 px-1 py-1.5">{who}</div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href={workspace ? `/w/${workspace.slug}/settings/profile` : "/settings"}>
                <UserIcon />
                Profile
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link href={workspace ? `/w/${workspace.slug}/settings` : "/settings"}>
                <SettingsIcon />
                Settings
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-muted-foreground text-xs font-medium">Theme</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme}>
              <DropdownMenuRadioItem value="light" onSelect={(e) => e.preventDefault()}>
                <SunIcon />
                Light
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dark" onSelect={(e) => e.preventDefault()}>
                <MoonIcon />
                Dark
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="system" onSelect={(e) => e.preventDefault()}>
                <MonitorIcon />
                System
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void signOut()}>
              <LogOutIcon />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
