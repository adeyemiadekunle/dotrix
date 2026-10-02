"use client";

import { Button } from "@pmagent/ui/components/button";
import { Checkbox } from "@pmagent/ui/components/checkbox";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { Input } from "@pmagent/ui/components/input";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CircleDotIcon,
  Columns3Icon,
  DownloadIcon,
  SearchIcon,
  TableIcon,
  UserIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";
import { Suspense, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  AGENT_LABELS,
  AGENTS,
  AssigneeAvatar,
  PRIORITIES,
  PRIORITY_META,
  PriorityIcon,
  STATUSES,
  STATUS_META,
  StatusIcon,
  TYPE_META,
  TypeIcon,
  type MemberMap,
} from "@/components/issues/meta";
import { formatDue, today } from "@/components/issues/workspace-issue-row";
import { EmptyState } from "@/components/states";
import { useAllIssues, useMembers, useUpdateIssue, type IssueSummary } from "@/lib/issues";
import { can } from "@/lib/labels";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

interface Column {
  id: string;
  label: string;
  /** The value to sort by and to write in the CSV. */
  value: (issue: IssueSummary, members: MemberMap) => string | number;
  cell: (issue: IssueSummary, members: MemberMap) => ReactNode;
  optional?: boolean;
  className?: string;
}

const assigneeName = (issue: IssueSummary, members: MemberMap) =>
  issue.assignee_agent
    ? AGENT_LABELS[issue.assignee_agent]
    : issue.assignee_user_id
      ? (members.get(issue.assignee_user_id)?.display_name ?? "Former member")
      : "";

const COLUMNS: Column[] = [
  { id: "key", label: "Key", value: (i) => i.key, cell: (i) => <span className="text-muted-foreground font-mono text-xs">{i.key}</span> },
  { id: "title", label: "Issue", value: (i) => i.title, cell: (i) => i.title, className: "min-w-64 max-w-md truncate" },
  {
    id: "type",
    label: "Type",
    optional: true,
    value: (i) => TYPE_META[i.type].label,
    cell: (i) => (
      <span className="flex items-center gap-1.5">
        <TypeIcon type={i.type} className="size-3.5" />
        {TYPE_META[i.type].label}
      </span>
    ),
  },
  {
    id: "status",
    label: "Status",
    value: (i) => STATUSES.indexOf(i.status),
    cell: (i) => (
      <span className="flex items-center gap-1.5">
        <StatusIcon status={i.status} />
        {STATUS_META[i.status].label}
      </span>
    ),
  },
  {
    id: "assignee",
    label: "Assignee",
    optional: true,
    value: assigneeName,
    cell: (i, m) => (
      <span className="flex items-center gap-1.5">
        <AssigneeAvatar issue={i} members={m} className="size-5" />
        {assigneeName(i, m) || <span className="text-muted-foreground">No one</span>}
      </span>
    ),
  },
  {
    id: "priority",
    label: "Priority",
    optional: true,
    value: (i) => PRIORITIES.indexOf(i.priority),
    cell: (i) => (
      <span className="flex items-center gap-1.5">
        <PriorityIcon priority={i.priority} />
        {PRIORITY_META[i.priority].label}
      </span>
    ),
  },
  {
    id: "due",
    label: "Due",
    optional: true,
    value: (i) => i.due ?? "9999",
    cell: (i) =>
      i.due ? (
        <span className={i.status !== "done" && i.due < today() ? "font-medium text-red-600 dark:text-red-400" : ""}>
          {formatDue(i.due)}
        </span>
      ) : null,
  },
  { id: "parent", label: "Parent", optional: true, value: (i) => i.parent_key ?? "", cell: (i) => <span className="font-mono text-xs">{i.parent_key}</span> },
  {
    id: "labels",
    label: "Labels",
    optional: true,
    value: (i) => i.labels.join(", "),
    cell: (i) => <span className="text-muted-foreground text-xs">{i.labels.join(", ")}</span>,
  },
  { id: "estimate", label: "Estimate", optional: true, value: (i) => i.estimate ?? -1, cell: (i) => i.estimate ?? "" },
  {
    id: "updated",
    label: "Updated",
    optional: true,
    value: (i) => i.updated_at,
    cell: (i) => <span className="text-muted-foreground text-xs">{new Date(i.updated_at).toLocaleDateString()}</span>,
  },
];

const HIDDEN_KEY = "pmagent:table-hidden-columns";

function csv(rows: IssueSummary[], columns: Column[], members: MemberMap): string {
  const quote = (value: string | number) => `"${String(value).replace(/"/g, '""')}"`;
  const plain = (column: Column, issue: IssueSummary) => {
    if (column.id === "status") return STATUS_META[issue.status].label;
    if (column.id === "priority") return PRIORITY_META[issue.priority].label;
    if (column.id === "due") return issue.due ?? "";
    if (column.id === "estimate") return issue.estimate ?? "";
    return column.value(issue, members);
  };
  return [columns.map((c) => quote(c.label)).join(","), ...rows.map((r) => columns.map((c) => quote(plain(c, r))).join(","))].join("\n");
}

type Changes = Parameters<ReturnType<typeof useUpdateIssue>["mutateAsync"]>[0]["changes"];

/** Change the selected issues together: status, or who they're assigned to. */
function BulkBar({
  keys,
  members,
  canAssignCodingAgent,
  busy,
  onApply,
  onClear,
}: {
  keys: string[];
  members: MemberMap;
  canAssignCodingAgent: boolean;
  busy: boolean;
  onApply: (changes: Changes, what: string) => void;
  onClear: () => void;
}) {
  return (
    <div
      role="toolbar"
      aria-label="Selected issues"
      className="bg-brand-muted text-brand-muted-foreground flex flex-wrap items-center gap-2 px-4 py-2 text-sm md:px-6"
    >
      <span className="font-medium">{keys.length} selected</span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline" disabled={busy}>
            <CircleDotIcon />
            Status
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {STATUSES.map((status) => (
            <DropdownMenuItem key={status} onSelect={() => onApply({ status }, `moved to ${STATUS_META[status].label}`)}>
              <StatusIcon status={status} />
              {STATUS_META[status].label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline" disabled={busy}>
            <UserIcon />
            Assign
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
          <DropdownMenuItem onSelect={() => onApply({ assignee_user_id: null, assignee_agent: null }, "unassigned")}>
            Unassigned
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>People</DropdownMenuLabel>
          {[...members.values()]
            .filter((m) => m.role !== "guest")
            .map((m) => (
              <DropdownMenuItem
                key={m.user_id}
                onSelect={() => onApply({ assignee_user_id: m.user_id, assignee_agent: null }, `assigned to ${m.display_name}`)}
              >
                {m.display_name}
              </DropdownMenuItem>
            ))}
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Agents</DropdownMenuLabel>
          {AGENTS.map((agent) => (
            <DropdownMenuItem
              key={agent}
              disabled={agent === "coding-agent" && !canAssignCodingAgent}
              onSelect={() => onApply({ assignee_agent: agent, assignee_user_id: null }, `assigned to ${AGENT_LABELS[agent]}`)}
            >
              {AGENT_LABELS[agent]}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <span className="flex-1" />
      <Button size="sm" variant="ghost" onClick={onClear} disabled={busy}>
        <XIcon />
        Clear selection
      </Button>
    </div>
  );
}

function TablePage() {
  const { workspace, project, scope, canEdit } = useProjectScope();
  const update = useUpdateIssue(scope);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const issues = useAllIssues(scope);
  const members = useMembers(workspace?.id);
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);
  const [, openIssue] = useSearchParam("issue");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ id: string; desc: boolean } | null>(null);
  const [hidden, setHidden] = useState<string[]>([]);

  useEffect(() => {
    try {
      setHidden(JSON.parse(localStorage.getItem(HIDDEN_KEY) ?? "[]"));
    } catch {
      // storage blocked or garbled: show every column
    }
  }, []);
  function toggleColumn(id: string) {
    const next = hidden.includes(id) ? hidden.filter((h) => h !== id) : [...hidden, id];
    setHidden(next);
    try {
      localStorage.setItem(HIDDEN_KEY, JSON.stringify(next));
    } catch {
      // only a convenience
    }
  }

  const columns = COLUMNS.filter((c) => !hidden.includes(c.id));
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let list = (issues.data ?? []).filter(
      (i) => !needle || i.title.toLowerCase().includes(needle) || i.key.toLowerCase().includes(needle),
    );
    if (sort) {
      const column = COLUMNS.find((c) => c.id === sort.id)!;
      list = [...list].sort((a, b) => {
        const x = column.value(a, memberMap);
        const y = column.value(b, memberMap);
        const order = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
        return sort.desc ? -order : order;
      });
    }
    return list;
  }, [issues.data, query, sort, memberMap]);

  // Selection follows what's shown: an issue filtered out by the search isn't changed.
  const shownKeys = useMemo(() => new Set(rows.map((r) => r.key)), [rows]);
  const chosen = [...selected].filter((key) => shownKeys.has(key));
  const allChosen = rows.length > 0 && chosen.length === rows.length;

  function toggle(key: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function apply(changes: Changes, what: string) {
    setBusy(true);
    const results = await Promise.allSettled(chosen.map((key) => update.mutateAsync({ key, changes })));
    setBusy(false);
    const done = results.filter((r) => r.status === "fulfilled").length;
    if (done === chosen.length) {
      toast.success(`${done} ${done === 1 ? "issue" : "issues"} ${what}`);
      setSelected(new Set());
    } else if (done > 0) {
      toast.warning(`${done} of ${chosen.length} issues ${what}; the rest are still selected`);
      const failed = new Set(chosen.filter((_, i) => results[i]!.status === "rejected"));
      setSelected(failed);
    }
  }

  function download() {
    const blob = new Blob([csv(rows, columns, memberMap)], { type: "text/csv" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${project?.key ?? "issues"}-issues.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 md:px-6">
        <div className="relative w-full max-w-60">
          <SearchIcon className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search issues"
            aria-label="Search issues"
            className="h-8 pl-8"
          />
        </div>
        <span className="text-muted-foreground text-xs">{rows.length} issues</span>
        <span className="flex-1" />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="outline">
              <Columns3Icon />
              Columns
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Show columns</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {COLUMNS.filter((c) => c.optional).map((c) => (
              <DropdownMenuCheckboxItem
                key={c.id}
                checked={!hidden.includes(c.id)}
                onCheckedChange={() => toggleColumn(c.id)}
                onSelect={(e) => e.preventDefault()}
              >
                {c.label}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button size="sm" variant="outline" onClick={download} disabled={rows.length === 0}>
          <DownloadIcon />
          Export CSV
        </Button>
      </div>
      {canEdit && chosen.length > 0 && (
        <BulkBar
          keys={chosen}
          members={memberMap}
          canAssignCodingAgent={can(workspace, "agents:code")}
          busy={busy}
          onApply={(changes, what) => void apply(changes, what)}
          onClear={() => setSelected(new Set())}
        />
      )}
      {issues.isLoading && <Skeleton className="mx-4 h-64 md:mx-6" />}
      {issues.data?.length === 0 && (
        <div className="px-4 md:px-6">
          <EmptyState icon={TableIcon} title="No issues yet" description="Create one with New issue, or ask the agents to plan a feature." />
        </div>
      )}
      {issues.data && issues.data.length > 0 && (
        <div className="overflow-x-auto border-t">
          <table className="w-full border-collapse text-sm">
            <thead className="bg-muted/40">
              <tr>
                {canEdit && (
                  <th scope="col" className="w-10 border-b pr-0 pl-4 md:pl-6">
                    <Checkbox
                      aria-label="Select all issues"
                      checked={allChosen ? true : chosen.length > 0 ? "indeterminate" : false}
                      onCheckedChange={() => setSelected(allChosen ? new Set() : new Set(rows.map((r) => r.key)))}
                    />
                  </th>
                )}
                {columns.map((c) => (
                  <th key={c.id} scope="col" className="border-b px-3 py-0 text-left text-xs font-medium whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => setSort(sort?.id === c.id ? (sort.desc ? null : { id: c.id, desc: true }) : { id: c.id, desc: false })}
                      className="text-muted-foreground hover:text-foreground flex h-9 items-center gap-1"
                    >
                      {c.label}
                      {sort?.id === c.id && (sort.desc ? <ArrowDownIcon className="size-3" /> : <ArrowUpIcon className="size-3" />)}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((issue) => (
                <tr
                  key={issue.key}
                  onClick={() => openIssue(issue.key)}
                  className={cn("hover:bg-muted/50 cursor-pointer border-b", selected.has(issue.key) && "bg-muted/60")}
                >
                  {canEdit && (
                    <td className="w-10 pr-0 pl-4 md:pl-6" onClick={(e) => e.stopPropagation()}>
                      <Checkbox
                        aria-label={`Select ${issue.key}`}
                        checked={selected.has(issue.key)}
                        onCheckedChange={() => toggle(issue.key)}
                      />
                    </td>
                  )}
                  {columns.map((c) => (
                    <td key={c.id} className={cn("h-10 px-3 whitespace-nowrap", c.className)}>
                      {c.id === "title" ? (
                        <button type="button" className="truncate text-left hover:underline" onClick={() => openIssue(issue.key)}>
                          {issue.title}
                        </button>
                      ) : (
                        c.cell(issue, memberMap)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <TablePage />
    </Suspense>
  );
}
