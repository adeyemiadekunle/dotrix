"use client";

import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { ActivityIcon } from "lucide-react";
import { Suspense, useMemo } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import type { MemberMap } from "@/components/issues/meta";
import { EmptyState } from "@/components/states";
import { useProjectActivity, type ActivityItem } from "@/lib/activity";
import { useMembers } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

const FILTERS: Record<string, { label: string; keep: (item: ActivityItem) => boolean }> = {
  all: { label: "Everything", keep: () => true },
  issues: { label: "Issues", keep: (i) => i.kind.startsWith("issue.") },
  documents: { label: "Documents", keep: (i) => i.kind.startsWith("document.") },
  agents: { label: "Agents", keep: (i) => Boolean(i.actor_agent) || i.kind === "run.started" },
  approvals: { label: "Approvals", keep: (i) => i.kind === "approval.decided" },
};

function ActivityPage() {
  const { workspace, project, scope } = useProjectScope();
  const activity = useProjectActivity(scope);
  const members = useMembers(workspace?.id);
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);
  const [filterParam, setFilter] = useSearchParam("show");
  const filter = filterParam && filterParam in FILTERS ? filterParam : "all";
  const items = useMemo(
    () => (activity.data?.pages.flat() ?? []).filter(FILTERS[filter].keep),
    [activity.data, filter],
  );
  const base = workspace && project ? `/w/${workspace.slug}/p/${project.key}` : "";

  return (
    <div className="flex w-full max-w-3xl flex-col gap-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-muted-foreground flex-1 text-sm">What people and agents did in this project.</p>
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
      {items.length > 0 && <ActivityFeed items={items} members={memberMap} base={base} />}
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

export default function Page() {
  return (
    <Suspense>
      <ActivityPage />
    </Suspense>
  );
}
