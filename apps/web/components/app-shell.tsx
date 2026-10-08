"use client";

import { Button } from "@pmagent/ui/components/button";
import { Separator } from "@pmagent/ui/components/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@pmagent/ui/components/sidebar";
import { cn } from "@pmagent/ui/lib/utils";
import { useMutation } from "@tanstack/react-query";
import { BellIcon, CloudOffIcon, MailWarningIcon, SearchIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { AppSidebar } from "@/components/app-sidebar";
import { PaletteProvider, usePalette, useShortcutLabel } from "@/components/command-palette";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useNotificationCounts } from "@/lib/notifications";
import { useCurrentWorkspace, useMe, useWorkspaces } from "@/lib/queries";

const DISMISSED = "pmagent:verify-banner-dismissed";

/** A slim reminder to confirm the email address; it can be put away for the browser session. */
function VerifyEmailBanner() {
  const me = useMe();
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    try {
      setDismissed(sessionStorage.getItem(DISMISSED) === "1");
    } catch {
      // storage blocked: the banner just stays
    }
  }, []);
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/verify-email/resend")),
    onSuccess: () => toast.success("Verification email sent"),
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!me.data || me.data.email_verified || dismissed) return null;
  return (
    <div className="bg-warning-muted text-warning-foreground flex min-h-9 shrink-0 items-center gap-2 border-b py-1 pr-2 pl-4 text-[13px]">
      <MailWarningIcon className="size-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">
        Confirm your email address using the link we sent to {me.data.email}.
      </span>
      <Button
        size="xs"
        variant="ghost"
        className="font-semibold hover:bg-black/5 dark:hover:bg-white/10"
        disabled={resend.isPending}
        onClick={() => resend.mutate()}
      >
        Resend
      </Button>
      <Button
        size="icon-xs"
        variant="ghost"
        className="hover:bg-black/5 dark:hover:bg-white/10"
        aria-label="Dismiss"
        title="Hide until you next open the app"
        onClick={() => {
          setDismissed(true);
          try {
            sessionStorage.setItem(DISMISSED, "1");
          } catch {
            // nothing to remember it in; hidden until reload
          }
        }}
      >
        <XIcon />
      </Button>
    </div>
  );
}

/** Shown when the API can't be reached or fails, instead of placeholders that never fill in. */
function ConnectionErrorBanner() {
  const me = useMe();
  const workspaces = useWorkspaces();
  const failed = [me, workspaces].find((q) => q.isError && !q.isFetching);
  if (!failed) return null;
  return (
    <div className="bg-destructive/10 text-destructive flex shrink-0 items-center gap-2 border-b px-4 py-2 text-sm">
      <CloudOffIcon className="size-4 shrink-0" />
      <span className="flex-1">Couldn&apos;t load your account: {errorMessage(failed.error)}</span>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          void me.refetch();
          void workspaces.refetch();
        }}
      >
        Retry
      </Button>
    </div>
  );
}

/** Pages whose content fills the window and scrolls inside itself (a message list and its input). */
const FILL_WINDOW = /^\/w\/[^/]+\/chat$/;

/** The signed-in frame: sidebar, a top bar with the page title, and the page. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <SidebarProvider>
      <PaletteProvider>
        <AppSidebar />
        {/* Filling pages get exactly the window's height, so banners, header, and tabs take what
            they need and the page's own flex-1 area gets the rest (no hard-coded offsets). */}
        {/* min-w-0: a wide page part (the Table view) scrolls inside the page instead of
            stretching the page past the window and pushing the header's controls off screen. */}
        <SidebarInset className={cn("min-w-0", FILL_WINDOW.test(pathname) && "h-svh min-h-0 overflow-hidden")}>
          <ConnectionErrorBanner />
          <VerifyEmailBanner />
          {children}
        </SidebarInset>
      </PaletteProvider>
    </SidebarProvider>
  );
}

/** Search (⌘K) and the notifications bell, at the right of every page's top bar. */
function TopBarTools() {
  const palette = usePalette();
  const shortcut = useShortcutLabel();
  const { workspace } = useCurrentWorkspace();
  const counts = useNotificationCounts(workspace?.id);
  const waiting = counts.data?.unread ?? 0;
  return (
    <div className="flex items-center gap-1.5">
      <Button
        variant="outline"
        size="sm"
        onClick={palette.open}
        className="text-muted-foreground hidden w-48 justify-start font-normal lg:flex"
      >
        <SearchIcon />
        Search
        <kbd className="ml-auto rounded border px-1 font-mono text-[10px]">{shortcut}</kbd>
      </Button>
      <Button variant="ghost" size="icon-sm" onClick={palette.open} aria-label="Search" className="lg:hidden">
        <SearchIcon />
      </Button>
      {workspace && (
        <Button variant="ghost" size="icon-sm" className="relative" asChild>
          <Link
            href={`/w/${workspace.slug}/approvals`}
            aria-label={waiting ? `Open notifications (${waiting} waiting)` : "Open notifications"}
            title="Notifications"
          >
            <BellIcon />
            {waiting > 0 && <span className="bg-primary absolute top-1 right-1 size-2 rounded-full" />}
          </Link>
        </Button>
      )}
    </div>
  );
}

/** Each page's top bar: sidebar toggle, title (with optional breadcrumb before it), and actions. */
export function PageHeader({
  title,
  parent,
  actions,
  icon,
}: {
  title: ReactNode;
  parent?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <header className="bg-background sticky top-0 z-10 flex h-13 shrink-0 items-center gap-2 border-b px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />
      <div className="flex min-w-0 flex-1 items-center gap-1.5 text-sm">
        {parent && (
          <>
            <span className="text-muted-foreground truncate">{parent}</span>
            <span className="text-muted-foreground/60">/</span>
          </>
        )}
        {icon}
        <h1 className="truncate font-semibold">{title}</h1>
      </div>
      {actions}
      <TopBarTools />
    </header>
  );
}
