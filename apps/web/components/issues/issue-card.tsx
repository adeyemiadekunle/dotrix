"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { cn } from "@pmagent/ui/lib/utils";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarIcon } from "lucide-react";
import type { ComponentProps } from "react";

import type { IssueSummary } from "@/lib/issues";

import { AssigneeAvatar, PriorityIcon, TypeIcon, type MemberMap } from "./meta";

export function formatDue(due: string): { text: string; overdue: boolean } {
  const date = new Date(`${due}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return {
    text: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    overdue: date < today,
  };
}

export function IssueCard({
  issue,
  members,
  className,
  dragging,
  ...props
}: { issue: IssueSummary; members: MemberMap; dragging?: boolean } & ComponentProps<"div">) {
  const due = issue.due ? formatDue(issue.due) : null;
  return (
    <div
      className={cn(
        "bg-card hover:border-foreground/20 grid cursor-pointer gap-2 rounded-lg border p-3 text-sm shadow-xs transition-colors",
        dragging && "ring-primary/30 rotate-1 shadow-lg ring-2",
        className,
      )}
      {...props}
    >
      <p className="line-clamp-3 leading-snug">{issue.title}</p>
      {(issue.labels.length > 0 || issue.parent_key) && (
        <div className="flex flex-wrap gap-1">
          {issue.parent_key && (
            <Badge variant="outline" className="font-mono text-[10px]">
              {issue.parent_key}
            </Badge>
          )}
          {issue.labels.map((label) => (
            <Badge key={label} variant="secondary" className="text-[10px]">
              {label}
            </Badge>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <TypeIcon type={issue.type} />
        <span className="text-muted-foreground font-mono text-xs">{issue.key}</span>
        {due && (
          <span
            className={cn(
              "text-muted-foreground flex items-center gap-1 text-xs",
              due.overdue && issue.status !== "done" && "text-red-600 dark:text-red-400",
            )}
          >
            <CalendarIcon className="size-3" />
            {due.text}
          </span>
        )}
        <span className="flex-1" />
        {issue.estimate != null && (
          <span className="bg-muted rounded px-1.5 text-xs tabular-nums">{issue.estimate}</span>
        )}
        <PriorityIcon priority={issue.priority} />
        <AssigneeAvatar issue={issue} members={members} />
      </div>
    </div>
  );
}

/** A card that can be dragged within and between board columns. */
export function SortableIssueCard({
  issue,
  members,
  onOpen,
  disabled,
}: {
  issue: IssueSummary;
  members: MemberMap;
  onOpen: (key: string) => void;
  disabled?: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: issue.key,
    disabled,
  });
  return (
    <IssueCard
      ref={setNodeRef}
      issue={issue}
      members={members}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(isDragging && "opacity-40")}
      onClick={() => onOpen(issue.key)}
      {...attributes}
      {...listeners}
    />
  );
}
