import { Checkbox } from "@dotrix/ui/components/checkbox";
import { Label } from "@dotrix/ui/components/label";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { Suspense, useMemo } from "react";

import { IssueTimeline, ZoomToggle, type TimelineZoom } from "@/components/issues/timeline";
import { useAllIssues, useUpdateIssue } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam, useSetSearchParams } from "@/lib/url-state";

/** The project's issues on a calendar, from each one's start to its due date. */
function ProjectTimeline() {
  const { workspace, project, scope, canEdit } = useProjectScope();
  const issues = useAllIssues(scope);
  const update = useUpdateIssue(scope);
  const [zoomParam] = useSearchParam("zoom");
  const [doneParam] = useSearchParam("done");
  const setParams = useSetSearchParams();
  const zoom: TimelineZoom = zoomParam === "months" ? "months" : "weeks";
  const showDone = doneParam === "1";
  const shown = useMemo(() => (issues.data ?? []).filter((i) => showDone || i.status !== "done"), [issues.data, showDone]);

  if (!workspace || !project || !issues.data) return <Skeleton className="m-4 h-64 md:m-6" />;
  const base = `/w/${workspace.slug}/p/${project.key}/timeline`;
  const keep = new URLSearchParams({ ...(zoom === "months" ? { zoom } : {}), ...(showDone ? { done: "1" } : {}) });
  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-muted-foreground flex-1 text-sm">
          Each issue from its start to its due date. Set both in an issue; an issue with only a due date runs from when it was created.
        </p>
        <Label className="flex items-center gap-2 text-sm font-normal">
          <Checkbox checked={showDone} onCheckedChange={(c) => setParams({ done: c === true ? "1" : null })} />
          Show done
        </Label>
        <ZoomToggle zoom={zoom} onZoom={(z) => setParams({ zoom: z === "weeks" ? null : z })} />
      </div>
      <IssueTimeline
        issues={shown}
        zoom={zoom}
        href={(issue) => `${base}?${new URLSearchParams([...keep, ["issue", issue.key]])}`}
        onReschedule={canEdit ? (issue, changes) => update.mutate({ key: issue.key, changes }) : undefined}
      />
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <ProjectTimeline />
    </Suspense>
  );
}
