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
  ChevronDownIcon,
  ChevronsUpIcon,
  ChevronUpIcon,
  EqualIcon,
  FlaskConicalIcon,
  ListTreeIcon,
  SquareCheckIcon,
  UserIcon,
  ZapIcon,
  type LucideIcon,
} from "lucide-react";

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

export const STATUS_META: Record<IssueStatus, { label: string; dot: string; badge: string }> = {
  todo: { label: "To do", dot: "bg-slate-400", badge: "bg-muted text-muted-foreground" },
  in_progress: {
    label: "In progress",
    dot: "bg-sky-500",
    badge: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  },
  blocked: { label: "Blocked", dot: "bg-red-500", badge: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300" },
  review: {
    label: "In review",
    dot: "bg-amber-500",
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  },
  done: {
    label: "Done",
    dot: "bg-emerald-500",
    badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  },
};

export const PRIORITY_META: Record<Priority, { label: string; icon: LucideIcon; className: string }> = {
  urgent: { label: "Urgent", icon: ChevronsUpIcon, className: "text-red-600 dark:text-red-400" },
  high: { label: "High", icon: ChevronUpIcon, className: "text-orange-600 dark:text-orange-400" },
  medium: { label: "Medium", icon: EqualIcon, className: "text-amber-600 dark:text-amber-400" },
  low: { label: "Low", icon: ChevronDownIcon, className: "text-sky-600 dark:text-sky-400" },
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
        <meta.icon aria-label={`${meta.label} priority`} className={cn("size-4 shrink-0", meta.className, className)} />
      </TooltipTrigger>
      <TooltipContent>{meta.label} priority</TooltipContent>
    </Tooltip>
  );
}

export function StatusBadge({ status, className }: { status: IssueStatus; className?: string }) {
  const meta = STATUS_META[status];
  return (
    <span className={cn("inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium", meta.badge, className)}>
      {meta.label}
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
}: {
  issue: { assignee_user_id: string | null; assignee_agent: AgentAssignee | null };
  members: MemberMap;
  className?: string;
}) {
  const name = assigneeName(issue, members);
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
