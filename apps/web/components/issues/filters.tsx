"use client";

import type { Schemas } from "@pmagent/api-client";
import { Button } from "@pmagent/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { Input } from "@pmagent/ui/components/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@pmagent/ui/components/select";
import { cn } from "@pmagent/ui/lib/utils";
import { ChevronDownIcon, SearchIcon, UserIcon, XIcon } from "lucide-react";
import { useMemo } from "react";

import { useEpics, type BoardFilters, type IssueType, type Scope } from "@/lib/issues";
import { useMe } from "@/lib/queries";
import { useSearchParam, useSetSearchParams } from "@/lib/url-state";

import { AGENTS, AGENT_LABELS, ISSUE_TYPES, TYPE_META, TypeIcon } from "./meta";

const ANY = "__any";

// Filters that aren't set stay quiet (dashed); set ones are tinted so you can see what's narrowing the board.
const IDLE = "h-8 border-dashed bg-transparent shadow-none text-muted-foreground hover:text-foreground dark:bg-transparent";
const SET = "h-8 border-brand/30 bg-brand-muted text-brand-muted-foreground hover:bg-brand-muted/80 dark:bg-brand-muted";
const filterStyle = (on: boolean) => (on ? SET : IDLE);

/** Board filters live in the URL, so a filtered board can be shared and survives a reload. */
export function useFilters() {
  const me = useMe();
  const [search, setSearch] = useSearchParam("q");
  const [types, setTypes] = useSearchParam("type");
  const [assignee, setAssignee] = useSearchParam("assignee");
  const [epic, setEpic] = useSearchParam("epic");
  const [label, setLabel] = useSearchParam("label");
  const setParams = useSetSearchParams();

  const type = useMemo(() => (types ? (types.split(",") as IssueType[]) : []), [types]);
  const server: BoardFilters = useMemo(
    () => ({
      type,
      assignee: assignee === "me" ? me.data?.id : (assignee ?? undefined),
      epic: epic ?? undefined,
      label: label ?? undefined,
    }),
    [type, assignee, me.data?.id, epic, label],
  );
  return {
    server,
    search: search ?? "",
    setSearch,
    type,
    setType: (next: IssueType[]) => setTypes(next.join(",") || null),
    assignee,
    setAssignee,
    epic,
    setEpic,
    label,
    setLabel,
    active: Boolean(search || types || assignee || epic || label),
    clear: () => setParams({ q: null, type: null, assignee: null, epic: null, label: null }),
  };
}

export function IssueFilters({
  filters,
  members,
  labels,
  scope,
  showEpic = true,
}: {
  filters: ReturnType<typeof useFilters>;
  members: Schemas["MemberRead"][];
  labels: string[];
  scope: Scope | undefined;
  showEpic?: boolean;
}) {
  const epics = useEpics(scope);
  const typeLabel =
    filters.type.length === 0
      ? "All types"
      : filters.type.length === 1
        ? TYPE_META[filters.type[0]!].label
        : `${filters.type.length} types`;

  return (
    <div className="flex flex-wrap items-center gap-2 px-4 pt-3 md:px-6">
      <div className="relative w-full sm:w-56">
        <SearchIcon className="text-muted-foreground absolute top-2 left-2.5 size-4" />
        <Input
          value={filters.search}
          onChange={(e) => filters.setSearch(e.target.value || null)}
          placeholder="Search issues"
          className="h-8 pl-8 text-sm"
          aria-label="Search issues"
        />
      </div>

      <Button
        variant="outline"
        size="sm"
        className={filterStyle(filters.assignee === "me")}
        aria-pressed={filters.assignee === "me"}
        onClick={() => filters.setAssignee(filters.assignee === "me" ? null : "me")}
      >
        <UserIcon />
        Mine
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className={filterStyle(filters.type.length > 0)}>
            {typeLabel}
            <ChevronDownIcon className="opacity-50" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {ISSUE_TYPES.map((t) => (
            <DropdownMenuCheckboxItem
              key={t}
              checked={filters.type.includes(t)}
              onSelect={(e) => e.preventDefault()}
              onCheckedChange={(on) =>
                filters.setType(on ? [...filters.type, t] : filters.type.filter((x) => x !== t))
              }
            >
              <TypeIcon type={t} />
              {TYPE_META[t].label}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <Select value={filters.assignee ?? ANY} onValueChange={(v) => filters.setAssignee(v === ANY ? null : v)}>
        <SelectTrigger size="sm" className={cn("w-40", filterStyle(Boolean(filters.assignee)))} aria-label="Assignee">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>Anyone</SelectItem>
          <SelectItem value="me">Assigned to me</SelectItem>
          <SelectItem value="none">Unassigned</SelectItem>
          <SelectSeparator />
          <SelectGroup>
            <SelectLabel>Agents</SelectLabel>
            {AGENTS.map((a) => (
              <SelectItem key={a} value={a}>
                {AGENT_LABELS[a]}
              </SelectItem>
            ))}
          </SelectGroup>
          {members.length > 0 && (
            <SelectGroup>
              <SelectLabel>People</SelectLabel>
              {members.map((m) => (
                <SelectItem key={m.user_id} value={m.user_id}>
                  {m.display_name}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
        </SelectContent>
      </Select>

      {showEpic && (epics.data?.length ?? 0) > 0 && (
        <Select value={filters.epic ?? ANY} onValueChange={(v) => filters.setEpic(v === ANY ? null : v)}>
          <SelectTrigger size="sm" className={cn("w-44", filterStyle(Boolean(filters.epic)))} aria-label="Epic">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All epics</SelectItem>
            {epics.data?.map((e) => (
              <SelectItem key={e.key} value={e.key}>
                <span className="text-muted-foreground font-mono text-xs">{e.key}</span> {e.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {(labels.length > 0 || filters.label) && (
        <Select value={filters.label ?? ANY} onValueChange={(v) => filters.setLabel(v === ANY ? null : v)}>
          <SelectTrigger size="sm" className={cn("w-36", filterStyle(Boolean(filters.label)))} aria-label="Label">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>All labels</SelectItem>
            {[...new Set([...labels, ...(filters.label ? [filters.label] : [])])].map((l) => (
              <SelectItem key={l} value={l}>
                {l}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {filters.active && (
        <Button variant="ghost" size="sm" className="h-8" onClick={filters.clear}>
          <XIcon />
          Clear
        </Button>
      )}
    </div>
  );
}
