"use client";

// How issue types, statuses, priorities, and assignees look everywhere they appear.
import type { Schemas } from "@pmagent/api-client";
import { Avatar, AvatarFallback } from "@pmagent/ui/components/avatar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@pmagent/ui/components/tooltip";
import { cn } from "@pmagent/ui/lib/utils";
import {
  BookmarkIcon,
  BotIcon,
  BugIcon,
  FlaskConicalIcon,
  ListTreeIcon,
  SquareCheckIcon,
  UserIcon,
  ZapIcon,
  type LucideIcon,
} from "lucide-react";
import type { ComponentType } from "react";

import type { AgentAssignee, IssueStatus, IssueType, Priority } from "@/lib/issues";
import { initials } from "@/lib/labels";

export const ISSUE_TYPES: IssueType[] = ["epic", "story", "task", "bug", "spike", "sub-task"];
export const STATUSES: IssueStatus[] = ["todo", "in_progress", "blocked", "review", "done"];
export const PRIORITIES: Priority[] = ["urgent", "high", "medium", "low"];
export const AGENTS: AgentAssignee[] = ["coding-agent", "claude-code", "codex"];

export const TYPE_META: Record<IssueType, { label: string; icon: LucideIcon; className: string }> = {
  epic: { label: "Epic", icon: ZapIcon, className: "text-violet-600 dark:text-violet-400" },
  story: { label: "Story", icon: BookmarkIcon, className: "text-emerald-600 dark:text-emerald-400" },
  task: { label: "Task", icon: SquareCheckIcon, className: "text-sky-600 dark:text-sky-400" },
  bug: { label: "Bug", icon: BugIcon, className: "text-red-600 dark:text-red-400" },
  spike: { label: "Spike", icon: FlaskConicalIcon, className: "text-amber-600 dark:text-amber-400" },
  "sub-task": { label: "Sub-task", icon: ListTreeIcon, className: "text-slate-500 dark:text-slate-400" },
};

export const STATUS_META: Record<IssueStatus, { label: string; className: string }> = {
  todo: { label: "To do", className: "text-slate-500 dark:text-slate-400" },
  in_progress: { label: "In progress", className: "text-blue-600 dark:text-blue-400" },
  blocked: { label: "Blocked", className: "text-red-600 dark:text-red-400" },
  review: { label: "In review", className: "text-amber-700 dark:text-amber-400" },
  done: { label: "Done", className: "text-emerald-700 dark:text-emerald-400" },
};

type IconProps = { className?: string };

// Each status has its own shape as well as its own colour, so it reads without colour vision.
const STATUS_SHAPES: Record<IssueStatus, ComponentType> = {
  todo: () => <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeDasharray="2.4 1.6" />,
  in_progress: () => (
    <>
      <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M7 3.2a3.8 3.8 0 0 1 0 7.6z" fill="currentColor" />
    </>
  ),
  blocked: () => (
    <>
      <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3.2 10.8l7.6-7.6" stroke="currentColor" strokeWidth="1.6" />
    </>
  ),
  review: () => (
    <>
      <circle cx="7" cy="7" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M7 4v3.2l2 1.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </>
  ),
  done: () => (
    <>
      <circle cx="7" cy="7" r="6" fill="currentColor" />
      <path
        d="M4.3 7.2l1.9 1.9 3.6-4"
        fill="none"
        className="stroke-background"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  ),
};

export function StatusIcon({ status, className }: { status: IssueStatus } & IconProps) {
  const Shape = STATUS_SHAPES[status];
  return (
    <svg viewBox="0 0 14 14" aria-hidden className={cn("size-3.5 shrink-0", STATUS_META[status].className, className)}>
      <Shape />
    </svg>
  );
}

/** Signal bars: `level` of three filled; the rest faint. */
function bars(level: 1 | 2 | 3) {
  function Bars({ className }: IconProps) {
    return (
      <svg viewBox="0 0 14 14" aria-hidden className={cn("size-3.5 shrink-0", className)}>
        {[
          [1, 8, 5],
          [5.5, 5, 8],
          [10, 2, 11],
        ].map(([x, y, h], i) => (
          <rect key={i} x={x} y={y} width="3" height={h} rx="1" fill="currentColor" opacity={i < level ? 1 : 0.25} />
        ))}
      </svg>
    );
  }
  return Bars;
}

function UrgentIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 14 14" aria-hidden className={cn("size-3.5 shrink-0", className)}>
      <rect x="1" y="1" width="12" height="12" rx="3" fill="currentColor" />
      <path d="M7 4v3.6" className="stroke-background" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="7" cy="10" r="0.95" className="fill-background" />
    </svg>
  );
}

// Colour only where priority matters (high, urgent), so orange and red keep their meaning.
export const PRIORITY_META: Record<Priority, { label: string; icon: ComponentType<IconProps>; className: string }> = {
  urgent: { label: "Urgent", icon: UrgentIcon, className: "text-red-600 dark:text-red-400" },
  high: { label: "High", icon: bars(3), className: "text-orange-600 dark:text-orange-400" },
  medium: { label: "Medium", icon: bars(2), className: "text-muted-foreground" },
  low: { label: "Low", icon: bars(1), className: "text-muted-foreground" },
};

export const AGENT_LABELS: Record<AgentAssignee, string> = {
  "coding-agent": "Coding agent",
  "claude-code": "Claude Code",
  codex: "Codex",
};

export function TypeIcon({ type, className }: { type: IssueType; className?: string }) {
  const meta = TYPE_META[type];
  return <meta.icon aria-label={meta.label} className={cn("size-4 shrink-0", meta.className, className)} />;
}

export function PriorityIcon({ priority, className }: { priority: Priority; className?: string }) {
  const meta = PRIORITY_META[priority];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span role="img" aria-label={`${meta.label} priority`} className="inline-flex">
          <meta.icon className={cn(meta.className, className)} />
        </span>
      </TooltipTrigger>
      <TooltipContent>{meta.label} priority</TooltipContent>
    </Tooltip>
  );
}

/** A status as its shape and name, the same on the board, the backlog, and the drawer. */
export function StatusBadge({ status, className }: { status: IssueStatus; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs whitespace-nowrap", className)}>
      <StatusIcon status={status} />
      {STATUS_META[status].label}
    </span>
  );
}

export type MemberMap = Map<string, Schemas["MemberRead"]>;

export function assigneeName(
  issue: { assignee_user_id: string | null; assignee_agent: AgentAssignee | null },
  members: MemberMap,
): string | null {
  if (issue.assignee_agent) return AGENT_LABELS[issue.assignee_agent];
  if (issue.assignee_user_id) return members.get(issue.assignee_user_id)?.display_name ?? "Former member";
  return null;
}

export function AssigneeAvatar({
  issue,
  members,
  className,
  showUnassigned = false,
}: {
  issue: { assignee_user_id: string | null; assignee_agent: AgentAssignee | null };
  members: MemberMap;
  className?: string;
  /** Draw an empty placeholder when nobody is assigned (lists that line up in columns); else nothing. */
  showUnassigned?: boolean;
}) {
  const name = assigneeName(issue, members);
  if (!name && !showUnassigned) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Avatar className={cn("size-6", className)}>
          <AvatarFallback
            className={cn(
              "text-[10px]",
              issue.assignee_agent && "bg-brand text-brand-foreground",
              !name && "bg-transparent border border-dashed",
            )}
          >
            {issue.assignee_agent ? (
              <BotIcon className="size-3.5" />
            ) : name ? (
              initials(name)
            ) : (
              <UserIcon className="text-muted-foreground size-3.5" />
            )}
          </AvatarFallback>
        </Avatar>
      </TooltipTrigger>
      <TooltipContent>{name ?? "Unassigned"}</TooltipContent>
    </Tooltip>
  );
}
