import { cn } from "@pmagent/ui/lib/utils";
import { Link } from "@/lib/navigation";

import { ProjectTile } from "@/components/project-tile";
import { PriorityIcon, StatusIcon, STATUS_META } from "@/components/issues/meta";
import type { WorkspaceIssue } from "@/lib/issues";

/** A day as `YYYY-MM-DD` in the browser's time zone (today, or `offset` days from it), to compare with due dates. */
export function today(offset = 0): string {
  const day = new Date();
  day.setDate(day.getDate() + offset);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}

/** "Today", or a short date ("Oct 4"); the year only when it isn't this year. */
export function formatDue(due: string): string {
  if (due === today()) return "Today";
  const date = new Date(`${due}T00:00:00`);
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) });
}

/** An issue from any project: opens in its project's board with the issue drawer. */
export function WorkspaceIssueRow({
  issue,
  workspaceSlug,
  showStatus = false,
}: {
  issue: WorkspaceIssue;
  workspaceSlug: string;
  showStatus?: boolean;
}) {
  const overdue = issue.due !== null && issue.status !== "done" && issue.due < today();
  return (
    <Link
      href={`/w/${workspaceSlug}/p/${issue.project_key}/board?issue=${issue.key}`}
      className="hover:bg-muted/60 flex min-h-11 items-center gap-3 border-b px-4 py-2 text-sm last:border-b-0"
    >
      <StatusIcon status={issue.status} />
      <span className="text-muted-foreground w-16 shrink-0 font-mono text-xs">{issue.key}</span>
      <span className="min-w-0 flex-1 truncate">{issue.title}</span>
      <span className="text-muted-foreground hidden items-center gap-1.5 text-xs sm:flex">
        <ProjectTile projectKey={issue.project_key} className="size-4 text-[8px]" />
        <span className="max-w-36 truncate">{issue.project_name}</span>
      </span>
      {showStatus && (
        <span className="text-muted-foreground hidden w-24 text-xs md:inline">{STATUS_META[issue.status].label}</span>
      )}
      <PriorityIcon priority={issue.priority} className="hidden sm:block" />
      <span
        className={cn(
          "w-14 shrink-0 text-right text-xs",
          overdue ? "font-medium text-red-600 dark:text-red-400" : "text-muted-foreground",
        )}
      >
        {issue.due ? formatDue(issue.due) : ""}
      </span>
    </Link>
  );
}
