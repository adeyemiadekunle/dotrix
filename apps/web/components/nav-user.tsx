import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@dotrix/ui/components/dropdown-menu";
import { SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar } from "@dotrix/ui/components/sidebar";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import {
  ArrowLeftRightIcon,
  CheckIcon,
  ChevronsUpDownIcon,
  KeyboardIcon,
  LogOutIcon,
  MonitorIcon,
  MoonIcon,
  SettingsIcon,
  SunIcon,
  TerminalIcon,
  UserIcon,
} from "lucide-react";
import { Link } from "@/lib/navigation";
import { useTheme } from "next-themes";
import { useState } from "react";

import { ConnectCliDialog, KeyboardShortcutsDialog } from "@/components/user-menu-dialogs";
import { UserAvatar } from "@/components/user-avatar";
import { authPost } from "@/lib/api";
import { myAvatarSrc } from "@/lib/profile";
import { useCurrentWorkspace, useMe, useWorkspaces } from "@/lib/queries";

async function signOut() {
  await authPost("logout").catch(() => undefined);
  window.location.assign("/login");
}

export function NavUser() {
  const { isMobile } = useSidebar();
  const me = useMe();
  const { workspace } = useCurrentWorkspace();
  const workspaces = useWorkspaces();
  const { theme, setTheme } = useTheme();
  const [dialog, setDialog] = useState<"shortcuts" | "cli" | null>(null);
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
            {(workspaces.data?.length ?? 0) > 1 && (
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <ArrowLeftRightIcon />
                  Switch workspace
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent className="max-h-80 min-w-48 overflow-y-auto">
                  {workspaces.data?.map((w) => (
                    <DropdownMenuItem key={w.id} asChild>
                      <Link href={`/w/${w.slug}`}>
                        <span className="min-w-0 flex-1 truncate">{w.name}</span>
                        {w.id === workspace?.id && <CheckIcon className="ml-auto" />}
                      </Link>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            )}
            <DropdownMenuItem onSelect={() => setDialog("shortcuts")}>
              <KeyboardIcon />
              Keyboard shortcuts
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setDialog("cli")}>
              <TerminalIcon />
              Connect the CLI
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
        <KeyboardShortcutsDialog open={dialog === "shortcuts"} onOpenChange={(open) => !open && setDialog(null)} />
        <ConnectCliDialog
          open={dialog === "cli"}
          onOpenChange={(open) => !open && setDialog(null)}
          workspaceSlug={workspace?.slug}
        />
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
