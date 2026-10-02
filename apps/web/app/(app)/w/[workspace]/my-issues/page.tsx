"use client";

import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@pmagent/ui/components/tabs";
import { CalendarIcon, CheckCircle2Icon, ChevronDownIcon, ChevronRightIcon, ClockAlertIcon, InboxIcon, SunIcon } from "lucide-react";
import { Suspense, useMemo, useState, type ComponentType } from "react";

import { AfterHydration } from "@/components/after-hydration";
import { PageHeader } from "@/components/app-shell";
import { IssueTimeline, ZoomToggle, type TimelineZoom } from "@/components/issues/timeline";
import { today, WorkspaceIssueRow } from "@/components/issues/workspace-issue-row";
import { issueHref, WorkspaceIssueBoard, WorkspaceIssueTable } from "@/components/issues/workspace-issue-views";
import { EmptyState, NotFound } from "@/components/states";
import { useWorkspaceIssues, type WorkspaceIssue, type WorkspaceIssueFilters } from "@/lib/issues";
import { useCurrentWorkspace } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

const WHO: Record<string, { label: string; filters: WorkspaceIssueFilters }> = {
  assigned: { label: "Assigned to me", filters: { assignee: "me" } },
  watching: { label: "Watching", filters: { watching: true } },
  reported: { label: "Reported by me", filters: { reporter: "me" } },
};

interface Group {
  id: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  iconClass?: string;
  issues: WorkspaceIssue[];
  collapsed?: boolean;
}

function groupIssues(issues: WorkspaceIssue[]): Group[] {
  const now = today();
  const weekAgo = new Date(Date.now() - 7 * 24 * 3600 * 1000);
  const open = issues.filter((i) => i.status !== "done");
  return [
    {
      id: "overdue",
      label: "Overdue",
      icon: ClockAlertIcon,
      iconClass: "text-red-600 dark:text-red-400",
      issues: open.filter((i) => i.due !== null && i.due < now),
    },
    { id: "today", label: "Today", icon: SunIcon, issues: open.filter((i) => i.due === now) },
    { id: "upcoming", label: "Upcoming", icon: CalendarIcon, issues: open.filter((i) => i.due !== null && i.due > now) },
    { id: "undated", label: "No due date", icon: InboxIcon, issues: open.filter((i) => i.due === null) },
    {
      id: "done",
      label: "Done this week",
      icon: CheckCircle2Icon,
      iconClass: "text-emerald-600 dark:text-emerald-400",
      issues: issues.filter((i) => i.status === "done" && new Date(i.updated_at) >= weekAgo),
      collapsed: true,
    },
  ];
}

const VIEWS = [
  ["list", "List"],
  ["board", "Board"],
  ["table", "Table"],
  ["timeline", "Timeline"],
] as const;
type View = (typeof VIEWS)[number][0];

function MyIssues() {
  const { workspace, notFound } = useCurrentWorkspace();
  const [viewParam, setView] = useSearchParam("view");
  const view: View = VIEWS.some(([id]) => id === viewParam) ? (viewParam as View) : "list";
  const [zoomParam, setZoom] = useSearchParam("zoom");
  const zoom: TimelineZoom = zoomParam === "months" ? "months" : "weeks";
  const [whoParam, setWho] = useSearchParam("who");
  const who = whoParam && whoParam in WHO ? whoParam : "assigned";
  const issues = useWorkspaceIssues(workspace && workspace.role !== "guest" ? workspace.id : undefined, WHO[who].filters);
  const groups = useMemo(() => groupIssues(issues.data ?? []), [issues.data]);
  // The other views show the same issues as the list: open ones, and what was done this week.
  const current = useMemo(() => groups.flatMap((g) => g.issues), [groups]);
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  if (notFound) return <NotFound what="workspace" />;
  const counts = Object.fromEntries(groups.map((g) => [g.id, g.issues.length]));
  return (
    <>
      <PageHeader title="My issues" parent={workspace?.name} />
      <div className="flex w-full max-w-6xl flex-col gap-4 p-4 md:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-muted-foreground flex-1 text-sm">
            {issues.data
              ? `${counts.overdue} overdue · ${counts.today} due today · ${counts.upcoming} upcoming, across every project you can see.`
              : "Your issues from every project you can see."}
          </p>
          <div role="group" aria-label="View" className="bg-muted flex gap-0.5 rounded-lg p-0.5 text-xs font-medium">
            {VIEWS.map(([id, label]) => (
              <button
                key={id}
                type="button"
                aria-pressed={view === id}
                onClick={() => setView(id === "list" ? null : id)}
                className={
                  view === id
                    ? "bg-background text-foreground rounded-md px-2.5 py-1 shadow-sm"
                    : "text-muted-foreground hover:text-foreground rounded-md px-2.5 py-1"
                }
              >
                {label}
              </button>
            ))}
          </div>
          {view === "timeline" && <ZoomToggle zoom={zoom} onZoom={(z) => setZoom(z === "weeks" ? null : z)} />}
          <Tabs value={who} onValueChange={(value) => setWho(value === "assigned" ? null : value)}>
            <TabsList>
              {Object.entries(WHO).map(([id, { label }]) => (
                <TabsTrigger key={id} value={id}>
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>

        {issues.isLoading && <Skeleton className="h-48" />}
        {issues.data?.length === 0 && (
          <EmptyState
            icon={InboxIcon}
            title="Nothing here"
            description={
              who === "assigned"
                ? "Issues assigned to you in any project show up here."
                : who === "watching"
                  ? "Watch an issue from its drawer to follow it here."
                  : "Issues you create show up here."
            }
          />
        )}
        {workspace && issues.data && issues.data.length > 0 && view === "board" && (
          <WorkspaceIssueBoard issues={current} workspaceSlug={workspace.slug} />
        )}
        {workspace && issues.data && issues.data.length > 0 && view === "table" && (
          <WorkspaceIssueTable issues={current} workspaceSlug={workspace.slug} />
        )}
        {workspace && issues.data && issues.data.length > 0 && view === "timeline" && (
          <IssueTimeline issues={current} href={(i) => issueHref(workspace.slug, i as WorkspaceIssue)} zoom={zoom} groupByProject />
        )}
        {workspace &&
          issues.data &&
          issues.data.length > 0 &&
          view === "list" &&
          groups.map((group) => {
            if (group.issues.length === 0 && group.id !== "today") return null;
            const collapsed = toggled[group.id] ?? Boolean(group.collapsed);
            return (
              <section key={group.id} className="bg-card rounded-xl border">
                <button
                  type="button"
                  onClick={() => setToggled((t) => ({ ...t, [group.id]: !collapsed }))}
                  aria-expanded={!collapsed}
                  className="flex h-11 w-full items-center gap-2 px-4 text-sm font-semibold"
                >
                  {collapsed ? <ChevronRightIcon className="size-4" /> : <ChevronDownIcon className="size-4" />}
                  <group.icon className={`size-4 ${group.iconClass ?? "text-muted-foreground"}`} />
                  {group.label}
                  <span className="text-muted-foreground font-normal">{group.issues.length}</span>
                </button>
                {!collapsed && group.issues.length > 0 && (
                  <div className="border-t">
                    {group.issues.map((issue) => (
                      <WorkspaceIssueRow key={issue.key} issue={issue} workspaceSlug={workspace.slug} showStatus />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
      </div>
    </>
  );
}

export default function MyIssuesPage() {
  return (
    // Under a Suspense boundary: rendered after hydration so data fetched meanwhile can't make
    // it differ from the server's markup (see AfterHydration).
    <Suspense>
      <AfterHydration>
        <MyIssues />
      </AfterHydration>
    </Suspense>
  );
}
