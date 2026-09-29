"use client";

import type { Schemas } from "@pmagent/api-client";
import { Button } from "@pmagent/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { Input } from "@pmagent/ui/components/input";
import { cn } from "@pmagent/ui/lib/utils";
import { ListFilterIcon, SearchIcon, TagIcon, UserIcon, XIcon, ZapIcon, type LucideIcon } from "lucide-react";
import { useMemo, type ReactNode } from "react";

import { useEpics, type BoardFilters, type IssueType, type Scope } from "@/lib/issues";
import { useMe } from "@/lib/queries";
import { useSearchParam, useSetSearchParams } from "@/lib/url-state";

import { AGENTS, AGENT_LABELS, ISSUE_TYPES, TYPE_META, TypeIcon } from "./meta";

const ANY = "__any";

/** A set filter, shown as a chip you can remove. */
function FilterChip({ name, value, onRemove }: { name: string; value: string; onRemove: () => void }) {
  return (
    <span className="bg-brand-muted text-brand-muted-foreground inline-flex h-8 max-w-64 items-center gap-1.5 rounded-md pr-1 pl-2.5 text-[13px]">
      <span className="opacity-75">{name}</span>
      <span className="truncate font-medium">{value}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove the ${name.toLowerCase()} filter`}
        className="hover:bg-background/60 flex size-6 items-center justify-center rounded"
      >
        <XIcon className="size-3.5" />
      </button>
    </span>
  );
}

function Sub({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <Icon className="text-muted-foreground size-4" />
        {label}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="max-h-80 w-56 overflow-y-auto">{children}</DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

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
  const hasEpics = showEpic && (epics.data?.length ?? 0) > 0;
  const allLabels = [...new Set([...labels, ...(filters.label ? [filters.label] : [])])];

  const assigneeName = (id: string) =>
    id === "me"
      ? "Me"
      : id === "none"
        ? "Nobody"
        : (AGENT_LABELS[id as keyof typeof AGENT_LABELS] ?? members.find((m) => m.user_id === id)?.display_name ?? "Someone");
  const epicName = (key: string) => epics.data?.find((e) => e.key === key)?.title ?? key;

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
        variant={filters.assignee === "me" ? "secondary" : "outline"}
        size="sm"
        aria-pressed={filters.assignee === "me"}
        className={cn(filters.assignee === "me" && "bg-brand-muted text-brand-muted-foreground hover:bg-brand-muted/80")}
        onClick={() => filters.setAssignee(filters.assignee === "me" ? null : "me")}
      >
        <UserIcon />
        Mine
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="border-dashed">
            <ListFilterIcon />
            Filter
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-48">
          <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">Narrow the board by</DropdownMenuLabel>
          <Sub icon={TYPE_META.task.icon} label="Type">
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
          </Sub>
          <Sub icon={UserIcon} label="Assignee">
            <DropdownMenuRadioGroup
              value={filters.assignee ?? ANY}
              onValueChange={(v) => filters.setAssignee(v === ANY ? null : v)}
            >
              <DropdownMenuRadioItem value={ANY}>Anyone</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="me">Assigned to me</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="none">Unassigned</DropdownMenuRadioItem>
              <DropdownMenuSeparator />
              <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">Agents</DropdownMenuLabel>
              {AGENTS.map((a) => (
                <DropdownMenuRadioItem key={a} value={a}>
                  {AGENT_LABELS[a]}
                </DropdownMenuRadioItem>
              ))}
              {members.length > 0 && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">People</DropdownMenuLabel>
                  {members.map((m) => (
                    <DropdownMenuRadioItem key={m.user_id} value={m.user_id}>
                      {m.display_name}
                    </DropdownMenuRadioItem>
                  ))}
                </>
              )}
            </DropdownMenuRadioGroup>
          </Sub>
          {hasEpics && (
            <Sub icon={ZapIcon} label="Epic">
              <DropdownMenuRadioGroup value={filters.epic ?? ANY} onValueChange={(v) => filters.setEpic(v === ANY ? null : v)}>
                <DropdownMenuRadioItem value={ANY}>All epics</DropdownMenuRadioItem>
                {epics.data?.map((e) => (
                  <DropdownMenuRadioItem key={e.key} value={e.key}>
                    <span className="truncate">{e.title}</span>
                    <span className="text-muted-foreground ml-auto font-mono text-xs">{e.key}</span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </Sub>
          )}
          {allLabels.length > 0 && (
            <Sub icon={TagIcon} label="Label">
              <DropdownMenuRadioGroup value={filters.label ?? ANY} onValueChange={(v) => filters.setLabel(v === ANY ? null : v)}>
                <DropdownMenuRadioItem value={ANY}>All labels</DropdownMenuRadioItem>
                {allLabels.map((l) => (
                  <DropdownMenuRadioItem key={l} value={l}>
                    {l}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </Sub>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {filters.type.length > 0 && (
        <FilterChip
          name="Type"
          value={filters.type.map((t) => TYPE_META[t].label).join(", ")}
          onRemove={() => filters.setType([])}
        />
      )}
      {filters.assignee && filters.assignee !== "me" && (
        <FilterChip name="Assignee" value={assigneeName(filters.assignee)} onRemove={() => filters.setAssignee(null)} />
      )}
      {filters.epic && <FilterChip name="Epic" value={epicName(filters.epic)} onRemove={() => filters.setEpic(null)} />}
      {filters.label && <FilterChip name="Label" value={filters.label} onRemove={() => filters.setLabel(null)} />}

      {filters.active && (
        <Button variant="ghost" size="sm" onClick={filters.clear}>
          <XIcon />
          Clear
        </Button>
      )}
    </div>
  );
}
