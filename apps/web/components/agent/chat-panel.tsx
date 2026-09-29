"use client";

import { Button } from "@pmagent/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@pmagent/ui/components/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@pmagent/ui/components/tooltip";
import { useIsMobile } from "@pmagent/ui/hooks/use-mobile";
import { HistoryIcon, Maximize2Icon, MessageSquarePlusIcon, ShieldAlertIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { timeAgo } from "@/components/issues/issue-activity";
import { runTitle, useRecentThreads, useThread } from "@/lib/agent";
import { useMembers } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { can } from "@/lib/labels";

import { useChat } from "./chat-context";
import { Conversation } from "./conversation";
import { ThreadTitle } from "./thread-title";

/** Recent conversations to switch between, and "new conversation". */
export function ThreadMenu() {
  const { scope } = useProjectScope();
  const { threadId, setThreadId } = useChat();
  const threads = useRecentThreads(scope);
  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button size="icon" variant="ghost" className="size-8" aria-label="Conversations">
              <HistoryIcon />
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>Conversations</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuItem onSelect={() => setThreadId(null)}>
          <MessageSquarePlusIcon />
          New conversation
        </DropdownMenuItem>
        {(threads.data?.length ?? 0) > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-muted-foreground text-xs">Recent</DropdownMenuLabel>
            {threads.data!.slice(0, 15).map((t) => (
              <DropdownMenuItem
                key={t.threadId}
                onSelect={() => setThreadId(t.threadId)}
                className={t.threadId === threadId ? "bg-accent" : undefined}
              >
                {t.waiting && <ShieldAlertIcon className="text-warning" />}
                <span className="min-w-0 flex-1 truncate">{t.title}</span>
                <span className="text-muted-foreground shrink-0 text-xs">{timeAgo(t.updatedAt)}</span>
              </DropdownMenuItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function PanelBody({ onClose }: { onClose: () => void }) {
  const { workspace, project, scope } = useProjectScope();
  const { threadId, setThreadId } = useChat();
  const thread = useThread(scope, threadId);
  const first = thread.data?.[0];
  const title = first ? (first.title ?? runTitle(first)) : null;
  const members = useMembers(workspace?.id);
  const names = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m.display_name])), [members.data]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-1 border-b px-3">
        <span className="grid min-w-0 flex-1 leading-tight">
          {scope ? (
            <ThreadTitle scope={scope} threadId={threadId} fallback="Project manager" />
          ) : (
            <span className="text-sm font-medium">Project manager</span>
          )}
          {title && <span className="text-muted-foreground text-xs">Project manager</span>}
        </span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="icon" variant="ghost" className="size-8" aria-label="New conversation" onClick={() => setThreadId(null)}>
              <MessageSquarePlusIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>New conversation</TooltipContent>
        </Tooltip>
        <ThreadMenu />
        {workspace && project && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="icon" variant="ghost" className="size-8" asChild>
                <Link href={`/w/${workspace.slug}/p/${project.key}/chat`} aria-label="Open full page" onClick={onClose}>
                  <Maximize2Icon />
                </Link>
              </Button>
            </TooltipTrigger>
            <TooltipContent>Full page</TooltipContent>
          </Tooltip>
        )}
        <Button size="icon" variant="ghost" className="size-8" aria-label="Close chat" onClick={onClose}>
          <XIcon />
        </Button>
      </header>
      {scope && (
        <Conversation
          scope={scope}
          threadId={threadId}
          onThread={setThreadId}
          names={names}
          canChat={can(workspace, "agents:chat")}
          canDecide={can(workspace, "agents:approve")}
          compact
        />
      )}
    </div>
  );
}

/** Chat beside every project page: a column on wide screens, a sheet on phones. */
export function ChatPanel() {
  const { open, setOpen } = useChat();
  const mobile = useIsMobile();
  if (mobile) {
    return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent className="w-full gap-0 p-0 sm:max-w-md [&>button]:hidden">
          <SheetTitle className="sr-only">Project manager</SheetTitle>
          <SheetDescription className="sr-only">Chat with the project's agents</SheetDescription>
          <PanelBody onClose={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
    );
  }
  if (!open) return null;
  return (
    <aside className="bg-background sticky top-0 h-svh max-h-full w-[400px] shrink-0 border-l xl:w-[440px]">
      <PanelBody onClose={() => setOpen(false)} />
    </aside>
  );
}
