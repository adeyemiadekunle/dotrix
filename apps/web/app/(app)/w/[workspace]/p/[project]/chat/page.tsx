"use client";

import { Button } from "@pmagent/ui/components/button";
import { cn } from "@pmagent/ui/lib/utils";
import { MessageSquarePlusIcon, ShieldAlertIcon } from "lucide-react";
import { useMemo } from "react";

import { useChat } from "@/components/agent/chat-context";
import { ThreadMenu } from "@/components/agent/chat-panel";
import { Conversation } from "@/components/agent/conversation";
import { timeAgo } from "@/components/issues/issue-activity";
import { useRecentThreads } from "@/lib/agent";
import { useMembers } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";

/** The PM on a full page, with the conversation list beside it on wide screens. */
export default function ChatPage() {
  const { workspace, scope } = useProjectScope();
  const { threadId, setThreadId } = useChat();
  const threads = useRecentThreads(scope);
  const members = useMembers(workspace?.id);
  const names = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m.display_name])), [members.data]);
  const role = workspace?.role;

  return (
    // Exactly the screen below the header (3.5rem) and tabs, so only the messages scroll.
    <div className="flex h-[calc(100svh-6.125rem)] min-h-0 shrink-0">
      <aside className="hidden w-64 shrink-0 flex-col border-r md:flex">
        <div className="p-3">
          <Button variant="outline" size="sm" className="w-full justify-start" onClick={() => setThreadId(null)}>
            <MessageSquarePlusIcon />
            New conversation
          </Button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 pb-3" aria-label="Conversations">
          {threads.data?.map((t) => (
            <button
              key={t.threadId}
              type="button"
              onClick={() => setThreadId(t.threadId)}
              className={cn(
                "hover:bg-muted grid w-full gap-0.5 rounded-md px-2 py-1.5 text-left text-sm",
                t.threadId === threadId && "bg-muted",
              )}
            >
              <span className="flex items-center gap-1.5">
                {t.waiting && <ShieldAlertIcon className="text-warning size-3.5 shrink-0" />}
                <span className="truncate">{t.title}</span>
              </span>
              <span className="text-muted-foreground text-xs">{timeAgo(t.updatedAt)}</span>
            </button>
          ))}
          {threads.data?.length === 0 && <p className="text-muted-foreground px-2 text-xs">No conversations yet.</p>}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex justify-end px-3 pt-2 md:hidden">
          <ThreadMenu />
        </div>
        {scope && (
          <Conversation
            scope={scope}
            threadId={threadId}
            onThread={setThreadId}
            names={names}
            canChat={role !== undefined && role !== "guest"}
            canDecide={role !== undefined && role !== "guest"}
          />
        )}
      </div>
    </div>
  );
}
