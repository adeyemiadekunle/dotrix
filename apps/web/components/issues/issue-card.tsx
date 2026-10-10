import type { Schemas } from "@dotrix/api-client";
import { cn } from "@dotrix/ui/lib/utils";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CalendarIcon } from "lucide-react";
import type { ComponentProps } from "react";

import type { IssueSummary } from "@/lib/issues";

import { AssigneeAvatar, PriorityIcon, TypeIcon, type MemberMap } from "./meta";

export function formatDue(due: string): { text: string; overdue: boolean; soon: boolean; days: number } {
  const date = new Date(`${due}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((date.getTime() - today.getTime()) / 86_400_000);
  return {
    text: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    overdue: days < 0,
    soon: days >= 0 && days <= 3,
    days,
  };
}

export type EpicMap = Map<string, Schemas["EpicProgress"]>;

/** The epic an issue belongs to, by name (its key is in the tooltip). */
export function EpicTag({ epicKey, epics, className }: { epicKey: string; epics: EpicMap; className?: string }) {
  const title = epics.get(epicKey)?.title;
  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)} title={epicKey}>
      <span className="size-1.5 shrink-0 rounded-[2px] bg-violet-600 dark:bg-violet-400" />
      <span className="truncate">{title ?? epicKey}</span>
    </span>
  );
}

function DueTag({ due, done }: { due: string; done: boolean }) {
  const d = formatDue(due);
  const tone = done ? "plain" : d.overdue ? "overdue" : d.soon ? "soon" : "plain";
  const text = tone === "overdue" ? `Overdue ${-d.days}d` : tone === "soon" ? (d.days === 0 ? "Due today" : `Due in ${d.days}d`) : d.text;
  return (
    <span
      title={`Due ${d.text}`}
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-full px-1.5 text-[11px] whitespace-nowrap",
        tone === "plain" && "text-muted-foreground",
        tone === "soon" && "bg-amber-50 font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300",
        tone === "overdue" && "bg-red-50 font-medium text-red-700 dark:bg-red-950 dark:text-red-300",
      )}
    >
      <CalendarIcon className="size-3" />
      {text}
    </span>
  );
}

export function IssueCard({
  issue,
  members,
  epics,
  className,
  dragging,
  ...props
}: { issue: IssueSummary; members: MemberMap; epics: EpicMap; dragging?: boolean } & ComponentProps<"div">) {
  const done = issue.status === "done";
  const progress = issue.type === "epic" ? epics.get(issue.key) : undefined;
  return (
    <div
      className={cn(
        // minmax(0,1fr): the card never grows wider than its column, whatever its content.
        "bg-card hover:border-foreground/20 grid min-w-0 cursor-pointer grid-cols-[minmax(0,1fr)] gap-2.5 rounded-[10px] border px-3 py-2.5 text-sm shadow-xs transition-colors",
        dragging && "ring-primary/30 rotate-1 shadow-lg ring-2",
        className,
      )}
      {...props}
    >
      <p className={cn("line-clamp-3 leading-snug font-medium break-words", done && "text-muted-foreground")}>{issue.title}</p>
      {(issue.labels.length > 0 || (issue.due && !done)) && (
        <div className="flex flex-wrap gap-1">
          {issue.labels.map((label) => (
            <span key={label} className="text-foreground/80 inline-flex h-5 items-center rounded-full border px-2 text-[11px]">
              {label}
            </span>
          ))}
          {issue.due && !done && <DueTag due={issue.due} done={done} />}
        </div>
      )}
      {progress && progress.total > 0 && (
        <div className="flex items-center gap-2">
          <div className="bg-muted h-1 flex-1 overflow-hidden rounded-full">
            <div className="h-full rounded-full bg-violet-600 dark:bg-violet-400" style={{ width: `${progress.percent}%` }} />
          </div>
          <span className="text-muted-foreground text-[11px] tabular-nums">
            {progress.done} of {progress.total}
          </span>
        </div>
      )}
      <div className="text-muted-foreground flex min-w-0 items-center gap-2 text-xs">
        <TypeIcon type={issue.type} className="size-3.5" />
        <span className="font-mono whitespace-nowrap">{issue.key}</span>
        {issue.parent_key && <EpicTag epicKey={issue.parent_key} epics={epics} />}
        <span className="flex-1" />
        {issue.estimate != null && <span className="bg-muted rounded px-1.5 text-[11px] tabular-nums">{issue.estimate}</span>}
        {!done && <PriorityIcon priority={issue.priority} />}
        <AssigneeAvatar issue={issue} members={members} className="size-5" />
      </div>
    </div>
  );
}

/** A card that can be dragged within and between board columns. */
export function SortableIssueCard({
  issue,
  members,
  epics,
  onOpen,
  disabled,
}: {
  issue: IssueSummary;
  members: MemberMap;
  epics: EpicMap;
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
      epics={epics}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(isDragging && "opacity-40")}
      onClick={() => onOpen(issue.key)}
      {...attributes}
      {...listeners}
    />
  );
}
