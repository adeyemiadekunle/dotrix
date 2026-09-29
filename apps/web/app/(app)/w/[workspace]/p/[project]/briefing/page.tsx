"use client";

import { Button } from "@pmagent/ui/components/button";
import { ChatMessageMeta } from "@pmagent/ui/components/chat-message";
import { ChatScroller } from "@pmagent/ui/components/chat-scroller";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { Loader2Icon, NewspaperIcon, RefreshCwIcon } from "lucide-react";
import { Suspense, useMemo } from "react";

import { AgentReply } from "@/components/agent/agent-reply";
import { timeAgo } from "@/components/issues/issue-activity";
import { EmptyState } from "@/components/states";
import { isActive, useBriefing, useBriefings, type Run } from "@/lib/agent";
import { useMembers } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

function day(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

function isToday(iso: string): boolean {
  return new Date(iso).toDateString() === new Date().toDateString();
}

/** The daily briefing: where the project stands, what's blocked, and what's next. Read-only:
 * the PM reads the project and board, and never changes anything for a briefing. */
function BriefingPage() {
  const { workspace, scope } = useProjectScope();
  const briefings = useBriefings(scope);
  const create = useBriefing(scope);
  const members = useMembers(workspace?.id);
  const names = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m.display_name])), [members.data]);
  const [selectedId, select] = useSearchParam("briefing");
  const runs = briefings.data ?? [];
  const shown: Run | undefined = runs.find((r) => r.id === selectedId) ?? runs[0];
  const working = runs.some(isActive);
  const canBrief = workspace !== undefined && workspace.role !== "guest";
  const hasToday = runs.some((r) => isToday(r.created_at) && r.status === "completed");

  async function generate() {
    const run = await create.mutateAsync().catch(() => null);
    if (run) {
      await briefings.refetch();
      select(run.id);
    }
  }

  const generateButton = canBrief && (
    <Button size="sm" variant={hasToday ? "outline" : "default"} disabled={working || create.isPending} onClick={() => void generate()}>
      {working || create.isPending ? <Loader2Icon className="animate-spin" /> : hasToday ? <RefreshCwIcon /> : <NewspaperIcon />}
      {working ? "Writing the briefing…" : hasToday ? "New briefing" : "Get today's briefing"}
    </Button>
  );

  return (
    // Fills the window below the banners, header, and tabs (see AppShell), so only the briefing scrolls.
    <div className="flex min-h-0 flex-1">
      {/* Hidden until there is a briefing to list. */}
      <aside className={cn("hidden w-64 shrink-0 flex-col border-r", runs.length > 0 && "md:flex")}>
        <p className="text-muted-foreground px-4 pt-3 pb-1 text-xs font-medium">Past briefings</p>
        <nav className="flex-1 overflow-y-auto px-2 pb-3" aria-label="Past briefings">
          {briefings.isLoading && <Skeleton className="mx-2 h-10" />}
          {runs.map((run) => (
            <button
              key={run.id}
              type="button"
              onClick={() => select(run.id)}
              className={cn(
                "hover:bg-muted grid w-full gap-0.5 rounded-md px-2 py-1.5 text-left text-sm",
                run.id === shown?.id && "bg-muted",
              )}
            >
              <span className="flex items-center gap-1.5 truncate">
                {isActive(run) && <Loader2Icon className="text-muted-foreground size-3.5 shrink-0 animate-spin" />}
                {day(run.created_at)}
              </span>
              <span className="text-muted-foreground text-xs">
                {timeAgo(run.created_at)}
                {run.status === "failed" && " · failed"}
              </span>
            </button>
          ))}
          {!briefings.isLoading && runs.length === 0 && <p className="text-muted-foreground px-2 text-xs">None yet.</p>}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b px-4">
          <h2 className="min-w-0 flex-1 truncate text-sm font-medium">
            {shown ? `Daily briefing · ${day(shown.created_at)}` : "Daily briefing"}
          </h2>
          {runs.length > 1 && (
            <div className="md:hidden">
              <Select value={shown?.id} onValueChange={select}>
                <SelectTrigger size="sm" className="w-40" aria-label="Past briefings">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {runs.map((run) => (
                    <SelectItem key={run.id} value={run.id}>
                      {new Date(run.created_at).toLocaleDateString()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {runs.length > 0 && generateButton}
        </div>
        {briefings.isLoading ? (
          <div className="p-6">
            <Skeleton className="mx-auto h-40 max-w-3xl" />
          </div>
        ) : !shown || !scope ? (
          <div className="flex flex-1 p-4 md:p-6">
            <EmptyState
              icon={NewspaperIcon}
              title="No briefing yet"
              description="The PM reads the project and the board and tells you where things stand: progress, what's blocked, what's due, and what to do next. It never changes anything."
              action={generateButton || undefined}
            />
          </div>
        ) : (
          <ChatScroller followKey={shown.id} contentClassName="mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)] gap-4 p-4 md:p-6">
            <ChatMessageMeta>
              <NewspaperIcon />
              {shown.requested_by_id ? (names.get(shown.requested_by_id) ?? "Someone") : "Someone"} asked for it ·{" "}
              {timeAgo(shown.created_at)}
            </ChatMessageMeta>
            <AgentReply run={shown} scope={scope} canDecide={false} avatar={false} />
          </ChatScroller>
        )}
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <BriefingPage />
    </Suspense>
  );
}
