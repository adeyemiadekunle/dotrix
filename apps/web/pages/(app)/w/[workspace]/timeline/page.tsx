import { Checkbox } from "@dotrix/ui/components/checkbox";
import { Label } from "@dotrix/ui/components/label";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { ChartGanttIcon } from "lucide-react";
import { Suspense, useMemo } from "react";

import { PageHeader } from "@/components/app-shell";
import { IssueTimeline, ZoomToggle, type TimelineZoom } from "@/components/issues/timeline";
import { issueHref } from "@/components/issues/workspace-issue-views";
import { EmptyState, NotFound } from "@/components/states";
import { useUpdateAnyIssue, useWorkspaceIssues, type WorkspaceIssue } from "@/lib/issues";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";
import { useSearchParam, useSetSearchParams } from "@/lib/url-state";

/** Every project's dated issues on one calendar, grouped by project. */
function WorkspaceTimeline() {
  const { workspace, notFound } = useCurrentWorkspace();
  const canSee = Boolean(workspace && workspace.role !== "guest");
  const issues = useWorkspaceIssues(canSee ? workspace?.id : undefined, {});
  const update = useUpdateAnyIssue(workspace?.id);
  const projects = useProjects(workspace?.id);
  const [project] = useSearchParam("project");
  const [zoomParam] = useSearchParam("zoom");
  const [doneParam] = useSearchParam("done");
  const setParams = useSetSearchParams();
  const zoom: TimelineZoom = zoomParam === "months" ? "months" : "weeks";
  const showDone = doneParam === "1";
  const shown = useMemo(
    () =>
      // The same issues as a project's Timeline (epics included), so the two agree.
      (issues.data ?? []).filter((i) => (!project || i.project_key === project) && (showDone || i.status !== "done")),
    [issues.data, project, showDone],
  );

  if (notFound) return <NotFound what="workspace" />;
  return (
    <>
      <PageHeader title="Timeline" parent={workspace?.name} />
      <div className="flex w-full flex-col gap-4 p-4 md:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <select
            aria-label="Project"
            value={project ?? ""}
            onChange={(e) => setParams({ project: e.target.value || null })}
            className="bg-background h-8 rounded-md border px-2 text-sm"
          >
            <option value="">All projects</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.key}>
                {p.name}
              </option>
            ))}
          </select>
          <Label className="flex items-center gap-2 text-sm font-normal">
            <Checkbox checked={showDone} onCheckedChange={(c) => setParams({ done: c === true ? "1" : null })} />
            Show done
          </Label>
          <span className="flex-1" />
          <ZoomToggle zoom={zoom} onZoom={(z) => setParams({ zoom: z === "weeks" ? null : z })} />
        </div>
        {!issues.data && canSee && <Skeleton className="h-64" />}
        {!canSee && workspace && (
          <EmptyState icon={ChartGanttIcon} title="Nothing to show" description="Guests don't see the projects' issues." />
        )}
        {workspace && issues.data && (
          <IssueTimeline
            issues={shown}
            zoom={zoom}
            groupByProject={!project}
            href={(issue) => issueHref(workspace.slug, issue as WorkspaceIssue)}
            onReschedule={(issue, changes) =>
              update.mutate({ projectId: (issue as WorkspaceIssue).project_id, key: issue.key, changes })
            }
          />
        )}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <WorkspaceTimeline />
    </Suspense>
  );
}
