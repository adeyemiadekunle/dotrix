"use client";

import { cn } from "@pmagent/ui/lib/utils";
import { ArrowDownIcon, ArrowUpIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { PriorityIcon, PRIORITIES, StatusIcon, STATUSES, STATUS_META } from "@/components/issues/meta";
import { formatDue, today } from "@/components/issues/workspace-issue-row";
import { ProjectTile } from "@/components/project-tile";
import type { WorkspaceIssue } from "@/lib/issues";

export function issueHref(workspaceSlug: string, issue: Pick<WorkspaceIssue, "project_key" | "key">): string {
  return `/w/${workspaceSlug}/p/${issue.project_key}/board?issue=${issue.key}`;
}

function DueText({ issue }: { issue: WorkspaceIssue }) {
  if (!issue.due) return null;
  const overdue = issue.status !== "done" && issue.due < today();
  return <span className={cn("text-xs", overdue ? "text-destructive font-medium" : "text-muted-foreground")}>{formatDue(issue.due)}</span>;
}

/** Issues from any project in columns by status; each card opens the issue in its project. */
export function WorkspaceIssueBoard({ issues, workspaceSlug }: { issues: WorkspaceIssue[]; workspaceSlug: string }) {
  return (
    <div className="flex gap-3 overflow-x-auto pb-2 @2xl:items-start" aria-label="Board">
      {STATUSES.map((status) => {
        const column = issues.filter((i) => i.status === status);
        return (
          <section key={status} aria-label={STATUS_META[status].label} className="bg-muted/40 flex w-72 shrink-0 flex-col rounded-xl border">
            <h3 className="flex h-10 items-center gap-2 px-3 text-sm font-semibold">
              <StatusIcon status={status} />
              {STATUS_META[status].label}
              <span className="text-muted-foreground font-normal">{column.length}</span>
            </h3>
            <div className="grid gap-2 p-2 pt-0">
              {column.map((issue) => (
                <Link
                  key={`${issue.project_key}-${issue.key}`}
                  href={issueHref(workspaceSlug, issue)}
                  className="bg-card hover:border-foreground/20 grid gap-2 rounded-lg border p-3 text-sm shadow-xs"
                >
                  <span className="line-clamp-2">{issue.title}</span>
                  <span className="text-muted-foreground flex items-center gap-2 text-xs">
                    <ProjectTile projectKey={issue.project_key} className="size-4 text-[8px]" />
                    <span className="font-mono">{issue.key}</span>
                    <PriorityIcon priority={issue.priority} className="ml-auto" />
                    <DueText issue={issue} />
                  </span>
                </Link>
              ))}
              {column.length === 0 && <p className="text-muted-foreground px-1 py-3 text-center text-xs">Nothing here</p>}
            </div>
          </section>
        );
      })}
    </div>
  );
}

type SortKey = "key" | "title" | "project" | "status" | "priority" | "due" | "updated";

const COLUMNS: { key: SortKey; label: string; className?: string }[] = [
  { key: "key", label: "Key", className: "w-24" },
  { key: "title", label: "Title" },
  { key: "project", label: "Project", className: "hidden md:table-cell" },
  { key: "status", label: "Status", className: "w-32" },
  { key: "priority", label: "Priority", className: "hidden sm:table-cell w-28" },
  { key: "due", label: "Due", className: "w-24" },
  { key: "updated", label: "Updated", className: "hidden lg:table-cell w-28" },
];

function compare(a: WorkspaceIssue, b: WorkspaceIssue, key: SortKey): number {
  switch (key) {
    case "key":
      return a.project_key.localeCompare(b.project_key) || a.key.localeCompare(b.key, undefined, { numeric: true });
    case "title":
      return a.title.localeCompare(b.title);
    case "project":
      return a.project_name.localeCompare(b.project_name);
    case "status":
      return STATUSES.indexOf(a.status) - STATUSES.indexOf(b.status);
    case "priority":
      return PRIORITIES.indexOf(a.priority) - PRIORITIES.indexOf(b.priority);
    case "due":
      // Undated last either way round.
      return (a.due ?? "9999").localeCompare(b.due ?? "9999");
    case "updated":
      return b.updated_at.localeCompare(a.updated_at);
  }
}

/** Issues from any project as a sortable table; rows open the issue in its project. */
export function WorkspaceIssueTable({ issues, workspaceSlug }: { issues: WorkspaceIssue[]; workspaceSlug: string }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "due", desc: false });
  const rows = useMemo(() => {
    const sorted = [...issues].sort((a, b) => compare(a, b, sort.key));
    return sort.desc ? sorted.reverse() : sorted;
  }, [issues, sort]);
  return (
    <div className="bg-card overflow-x-auto rounded-xl border">
      <table className="w-full text-sm">
        <thead className="text-muted-foreground border-b text-left text-xs">
          <tr>
            {COLUMNS.map((column) => {
              const active = sort.key === column.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={active ? (sort.desc ? "descending" : "ascending") : undefined}
                  className={cn("px-3 py-2 font-medium", column.className)}
                >
                  <button
                    type="button"
                    onClick={() => setSort({ key: column.key, desc: active ? !sort.desc : false })}
                    className="hover:text-foreground flex items-center gap-1"
                  >
                    {column.label}
                    {active && (sort.desc ? <ArrowDownIcon className="size-3" /> : <ArrowUpIcon className="size-3" />)}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((issue) => {
            const href = issueHref(workspaceSlug, issue);
            return (
              <tr key={`${issue.project_key}-${issue.key}`} className="hover:bg-muted/50 border-b last:border-b-0">
                <td className="px-3 py-2 font-mono text-xs">
                  <Link href={href} className="hover:underline">
                    {issue.key}
                  </Link>
                </td>
                <td className="max-w-0 px-3 py-2">
                  <Link href={href} className="block truncate hover:underline">
                    {issue.title}
                  </Link>
                </td>
                <td className="hidden px-3 py-2 md:table-cell">
                  <span className="flex items-center gap-1.5 text-xs">
                    <ProjectTile projectKey={issue.project_key} className="size-4 text-[8px]" />
                    <span className="truncate">{issue.project_name}</span>
                  </span>
                </td>
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1.5 text-xs">
                    <StatusIcon status={issue.status} />
                    {STATUS_META[issue.status].label}
                  </span>
                </td>
                <td className="hidden px-3 py-2 sm:table-cell">
                  <PriorityIcon priority={issue.priority} />
                </td>
                <td className="px-3 py-2">
                  <DueText issue={issue} />
                </td>
                <td className="text-muted-foreground hidden px-3 py-2 text-xs lg:table-cell">
                  {new Date(issue.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
