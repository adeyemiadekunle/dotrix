"use client";

import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query";
import { ActivityIcon } from "lucide-react";
import { useMemo } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import type { MemberMap } from "@/components/issues/meta";
import { EmptyState } from "@/components/states";
import type { ActivityItem } from "@/lib/activity";
import { useMembers } from "@/lib/issues";
import { useSearchParam } from "@/lib/url-state";

const FILTERS: Record<string, { label: string; keep: (item: ActivityItem) => boolean }> = {
  all: { label: "Everything", keep: () => true },
  issues: { label: "Issues", keep: (i) => i.kind.startsWith("issue.") },
  documents: { label: "Documents", keep: (i) => i.kind.startsWith("document.") },
  agents: { label: "Agents", keep: (i) => Boolean(i.actor_agent) || i.kind === "run.started" },
  approvals: { label: "Approvals", keep: (i) => i.kind === "approval.decided" },
};

/** An activity page: filters (`?show=`), the feed grouped by day, and "Show older". */
export function ActivityView({
  activity,
  workspace,
  intro,
  showProject = false,
}: {
  activity: UseInfiniteQueryResult<InfiniteData<ActivityItem[], unknown>>;
  workspace: { id: string; slug: string } | undefined;
  intro: string;
  showProject?: boolean;
}) {
  const members = useMembers(workspace?.id);
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);
  const [filterParam, setFilter] = useSearchParam("show");
  const filter = filterParam && filterParam in FILTERS ? filterParam : "all";
  const items = useMemo(() => (activity.data?.pages.flat() ?? []).filter(FILTERS[filter].keep), [activity.data, filter]);

  return (
    <div className="flex w-full max-w-3xl flex-col gap-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-muted-foreground flex-1 text-sm">{intro}</p>
        <div role="group" aria-label="Show" className="bg-muted flex gap-0.5 rounded-lg p-0.5 text-xs font-medium">
          {Object.entries(FILTERS).map(([id, { label }]) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id === "all" ? null : id)}
              className={cn(
                "rounded-md px-2.5 py-1",
                filter === id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {activity.isLoading && <Skeleton className="h-64" />}
      {activity.data && items.length === 0 && (
        <EmptyState
          icon={ActivityIcon}
          title="Nothing yet"
          description="Issue changes, document edits, agent requests, and decisions show up here as they happen."
        />
      )}
      {items.length > 0 && workspace && (
        <ActivityFeed items={items} members={memberMap} workspaceSlug={workspace.slug} showProject={showProject} />
      )}
      {activity.hasNextPage && (
        <Button
          variant="outline"
          size="sm"
          className="self-center"
          disabled={activity.isFetchingNextPage}
          onClick={() => void activity.fetchNextPage()}
        >
          Show older
        </Button>
      )}
    </div>
  );
}
