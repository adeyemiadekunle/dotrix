import { Button } from "@pmagent/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { Separator } from "@pmagent/ui/components/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger, useSidebar } from "@pmagent/ui/components/sidebar";
import { cn } from "@pmagent/ui/lib/utils";
import { useMutation } from "@tanstack/react-query";
import {
  BellIcon,
  ChevronDownIcon,
  CircleCheckIcon,
  CloudOffIcon,
  EllipsisIcon,
  FolderKanbanIcon,
  FolderPlusIcon,
  HomeIcon,
  MailWarningIcon,
  MessageSquarePlusIcon,
  PlusIcon,
  SearchIcon,
  SquarePenIcon,
  UserPlusIcon,
  XIcon,
} from "lucide-react";
import { Link, usePathname } from "@/lib/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { AppSidebar } from "@/components/app-sidebar";
import { PaletteProvider, usePalette, useShortcutLabel } from "@/components/command-palette";
import { api, errorMessage, unwrap } from "@/lib/api";
import { can, canManageProjects } from "@/lib/labels";
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

/** Asks the open project to show its New issue dialog (the top bar's New menu). */
export const NEW_ISSUE_EVENT = "pmagent:new-issue";

/** The page fades in when you go somewhere else (not when only the query changes). */
function usePageEnter(pathname: string) {
  const ref = useRef<HTMLElement>(null);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    ref.current?.animate([{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "none" }], {
      duration: 220,
      easing: "cubic-bezier(0.23, 1, 0.32, 1)",
    });
  }, [pathname]);
  return ref;
}

/** The signed-in frame: sidebar, a top bar with the page title, the page, and on phones a bottom bar. */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const main = usePageEnter(pathname);
  return (
    <SidebarProvider>
      <PaletteProvider>
        <a
          href="#main-content"
          className="bg-foreground text-background fixed top-[-60px] left-3 z-[100] rounded-md px-3 py-2 text-[12.5px] font-medium transition-[top] focus:top-2"
        >
          Skip to content
        </a>
        <AppSidebar />
        {/* Filling pages get exactly the window's height (less the bottom bar on phones), so
            banners, header, and tabs take what they need and the page's own flex-1 area gets
            the rest (no hard-coded offsets). */}
        <SidebarInset
          ref={main}
          id="main-content"
          tabIndex={-1}
          className={cn(
            "pb-14 outline-none md:pb-0",
            FILL_WINDOW.test(pathname) && "h-svh min-h-0 overflow-hidden",
          )}
        >
          <ConnectionErrorBanner />
          <VerifyEmailBanner />
          {children}
        </SidebarInset>
        <BottomNav />
      </PaletteProvider>
    </SidebarProvider>
  );
}

/** Phones: the places you go most, a thumb's reach away; More opens the full sidebar. */
function BottomNav() {
  const pathname = usePathname();
  const { workspace } = useCurrentWorkspace();
  const { setOpenMobile } = useSidebar();
  const counts = useNotificationCounts(workspace?.id);
  if (!workspace) return null;
  const base = `/w/${workspace.slug}`;
  const items = [
    { href: base, label: "Home", icon: HomeIcon, on: pathname === base },
    { href: `${base}/my-issues`, label: "My issues", icon: CircleCheckIcon },
    { href: `${base}/projects`, label: "Projects", icon: FolderKanbanIcon },
    { href: `${base}/approvals`, label: "Notifications", icon: BellIcon, dot: (counts.data?.unread ?? 0) > 0 },
  ];
  return (
    <nav
      aria-label="Primary"
      className="bg-background/95 fixed inset-x-0 bottom-0 z-30 grid h-14 grid-cols-5 border-t pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      {items.map(({ href, label, icon: Icon, on, dot }) => {
        const active = on ?? pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex flex-col items-center justify-center gap-0.5 text-[10.5px] font-medium",
              active ? "text-foreground" : "text-muted-foreground",
            )}
          >
            <Icon className="size-[19px]" />
            {label}
            {dot && <span className="bg-primary absolute top-2 left-[calc(50%+6px)] size-1.5 rounded-full" />}
          </Link>
        );
      })}
      <button
        type="button"
        onClick={() => setOpenMobile(true)}
        className="text-muted-foreground flex flex-col items-center justify-center gap-0.5 text-[10.5px] font-medium"
      >
        <EllipsisIcon className="size-[19px]" />
        More
      </button>
    </nav>
  );
}

/** New ▾: what you can start from anywhere (an issue only inside a project). */
function NewMenu() {
  const pathname = usePathname();
  const { workspace } = useCurrentWorkspace();
  if (!workspace || workspace.role === "guest") return null;
  const base = `/w/${workspace.slug}`;
  const projectKey = pathname.match(/^\/w\/[^/]+\/p\/([^/]+)/)?.[1];
  const manages = canManageProjects(workspace.role);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" aria-label="Create new">
          <PlusIcon />
          <span className="hidden sm:inline">New</span>
          <ChevronDownIcon className="hidden size-3! opacity-60 sm:block" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {projectKey && (
          <DropdownMenuItem onSelect={() => window.dispatchEvent(new Event(NEW_ISSUE_EVENT))}>
            <SquarePenIcon />
            New issue
          </DropdownMenuItem>
        )}
        {can(workspace, "agents:chat") && (
          <DropdownMenuItem asChild>
            <Link href={`${base}/chat${projectKey ? `?project=${projectKey}` : ""}`}>
              <MessageSquarePlusIcon />
              New chat
            </Link>
          </DropdownMenuItem>
        )}
        {manages && (
          <DropdownMenuItem asChild>
            <Link href={`${base}/projects/new`}>
              <FolderPlusIcon />
              New project
            </Link>
          </DropdownMenuItem>
        )}
        {manages && workspace.kind === "organization" && (
          <DropdownMenuItem asChild>
            <Link href={`${base}/settings/invites`}>
              <UserPlusIcon />
              Invite people
            </Link>
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
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
        variant="ghost"
        size="sm"
        onClick={palette.open}
        className="bg-secondary text-muted-foreground hover:text-foreground hidden w-56 justify-start border-border font-normal lg:flex"
      >
        <SearchIcon />
        Search or jump to…
        <kbd className="bg-card ml-auto rounded border px-1 font-mono text-[10px]">{shortcut}</kbd>
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
            {waiting > 0 && <span className="bg-primary ring-background absolute top-1 right-1 size-[7px] rounded-full ring-2" />}
          </Link>
        </Button>
      )}
      <NewMenu />
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
    <header className="bg-background/95 sticky top-0 z-10 flex h-[46px] shrink-0 items-center gap-2 border-b px-4 backdrop-blur md:px-gutter">
      <SidebarTrigger className="-ml-1.5" />
      <Separator orientation="vertical" className="mr-1.5 data-[orientation=vertical]:h-4" />
      <nav aria-label="Breadcrumb" className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px]">
        {parent && (
          <>
            <span className="text-muted-foreground truncate">{parent}</span>
            <span className="text-muted-foreground/50">/</span>
          </>
        )}
        {icon}
        <h1 className="truncate font-medium">{title}</h1>
      </nav>
      {actions}
      <TopBarTools />
    </header>
  );
}
