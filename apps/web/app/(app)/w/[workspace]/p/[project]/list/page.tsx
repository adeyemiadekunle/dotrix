"use client";

import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Progress } from "@pmagent/ui/components/progress";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { ChevronDownIcon, ChevronRightIcon, GripVerticalIcon, ListOrderedIcon, ListTodoIcon } from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { EpicTag, type EpicMap } from "@/components/issues/issue-card";
import { AssigneeAvatar, PriorityIcon, STATUS_META, StatusIcon, TypeIcon, type MemberMap } from "@/components/issues/meta";
import { formatDue, today } from "@/components/issues/workspace-issue-row";
import { EmptyState } from "@/components/states";
import { useBacklog, useBoard, useEpics, useMembers, useMoveIssue, type IssueSummary } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

/** One issue, laid out like a row on My issues: status, key, title, epic, priority, due, assignee. */
function Row({
  issue,
  members,
  epics,
  onOpen,
  draggable,
  showStatus,
}: {
  issue: IssueSummary;
  members: MemberMap;
  epics: EpicMap;
  onOpen: (key: string) => void;
  draggable: boolean;
  showStatus: boolean;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: issue.key,
    disabled: !draggable,
  });
  const overdue = issue.due !== null && issue.status !== "done" && issue.due < today();
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        "bg-card hover:bg-muted/60 flex min-h-11 items-center gap-3 border-b px-4 py-2 text-sm last:border-b-0",
        isDragging && "relative z-10 shadow-lg",
      )}
    >
      {draggable && (
        <button
          ref={setActivatorNodeRef}
          type="button"
          aria-label={`Reorder ${issue.key}`}
          className="text-muted-foreground hover:text-foreground -ml-1 cursor-grab touch-none active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVerticalIcon className="size-4" />
        </button>
      )}
      <button type="button" className="flex min-w-0 flex-1 items-center gap-3 text-left" onClick={() => onOpen(issue.key)}>
        <StatusIcon status={issue.status} />
        <span className="text-muted-foreground w-16 shrink-0 font-mono text-xs">{issue.key}</span>
        <TypeIcon type={issue.type} className="hidden sm:block" />
        <span className="min-w-0 flex-1 truncate">{issue.title}</span>
        {issue.parent_key && (
          <EpicTag
            epicKey={issue.parent_key}
            epics={epics}
            className="text-muted-foreground hidden max-w-40 text-xs md:flex"
          />
        )}
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
      </button>
      <AssigneeAvatar issue={issue} members={members} showUnassigned />
    </li>
  );
}

/** A card of issues with a header that folds it away, as on My issues. */
function Group({
  icon,
  label,
  count,
  collapsed,
  onToggle,
  children,
}: {
  icon: ReactNode;
  label: string;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section className="bg-card overflow-hidden rounded-xl border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        className="flex h-11 w-full items-center gap-2 px-4 text-sm font-semibold"
      >
        {collapsed ? <ChevronRightIcon className="size-4" /> : <ChevronDownIcon className="size-4" />}
        {icon}
        {label}
        <span className="text-muted-foreground font-normal">{count}</span>
      </button>
      {!collapsed && count > 0 && <ul className="border-t">{children}</ul>}
    </section>
  );
}

function ListPage() {
  const { workspace, scope, canEdit } = useProjectScope();
  const backlog = useBacklog(scope);
  const epics = useEpics(scope);
  const members = useMembers(workspace?.id);
  const move = useMoveIssue(scope);
  const [, openIssue] = useSearchParam("issue");
  const [epic, setEpic] = useSearchParam("epic");
  const [group, setGroup] = useSearchParam("group");
  const byStatus = group === "status";
  const board = useBoard(byStatus ? scope : undefined, epic ? { epic } : {});
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);
  const epicMap: EpicMap = useMemo(() => new Map(epics.data?.map((e) => [e.key, e])), [epics.data]);
  // Folded groups; Done starts folded, as on My issues.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const isCollapsed = (id: string) => toggled[id] ?? id === "done";
  const toggle = (id: string) => setToggled((t) => ({ ...t, [id]: !isCollapsed(id) }));

  // Local order so a drop shows at once; replaced when the refetch arrives.
  const [items, setItems] = useState<IssueSummary[]>([]);
  const dragging = useRef(false);
  useEffect(() => {
    if (!dragging.current) setItems(backlog.data ?? []);
  }, [backlog.data]);

  const visible = epic ? items.filter((i) => i.parent_key === epic || i.key === epic) : items;
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function onDragEnd({ active, over }: DragEndEvent) {
    dragging.current = false;
    if (!over || active.id === over.id) return;
    const from = visible.findIndex((i) => i.key === active.id);
    const to = visible.findIndex((i) => i.key === over.id);
    const reordered = arrayMove(visible, from, to);
    const next = reordered[to + 1];
    const prev = reordered[to - 1];
    // Rank against the visible neighbour; with an epic filter that's the next issue in the epic.
    setItems((all) => {
      const without = all.filter((i) => i.key !== active.id);
      const moving = all.find((i) => i.key === active.id)!;
      const at = next ? without.findIndex((i) => i.key === next.key) : without.findIndex((i) => i.key === prev!.key) + 1;
      return [...without.slice(0, at), moving, ...without.slice(at)];
    });
    move.mutate({ key: String(active.id), rank: next ? { before: next.key } : { after: prev!.key } });
  }

  return (
    <div className="grid flex-1 content-start gap-6 p-4 md:p-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <section className="grid content-start gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-medium">{byStatus ? "By status" : "Backlog"}</h2>
          <span className="text-muted-foreground flex-1 text-sm">
            {byStatus
              ? `Every issue${epic ? ` in ${epic}` : ""}, grouped by status`
              : `${visible.length} open${epic ? ` in ${epic}` : ""} · highest first, drag to reorder`}
          </span>
          <div role="group" aria-label="Group" className="bg-muted flex gap-0.5 rounded-lg p-0.5 text-xs font-medium">
            {[
              ["none", "Ranked"],
              ["status", "By status"],
            ].map(([id, label]) => {
              const on = (id === "status") === byStatus;
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setGroup(id === "status" ? "status" : null)}
                  className={cn(
                    "rounded-md px-2.5 py-1",
                    on ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
        {byStatus ? (
          board.isLoading ? (
            <Skeleton className="h-64" />
          ) : (
            board.data?.columns.map((column) => (
              <Group
                key={column.status}
                icon={<StatusIcon status={column.status} />}
                label={STATUS_META[column.status].label}
                count={column.issues.length}
                collapsed={isCollapsed(column.status)}
                onToggle={() => toggle(column.status)}
              >
                {/* Rows are sortable items; grouped by status they don't move, so the context is inert. */}
                <DndContext>
                  <SortableContext items={column.issues.map((i) => i.key)} strategy={verticalListSortingStrategy}>
                    {column.issues.map((issue) => (
                      <Row
                        key={issue.key}
                        issue={issue}
                        members={memberMap}
                        epics={epicMap}
                        onOpen={openIssue}
                        draggable={false}
                        showStatus={false}
                      />
                    ))}
                  </SortableContext>
                </DndContext>
              </Group>
            ))
          )
        ) : backlog.isLoading ? (
          <Skeleton className="h-64" />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={ListTodoIcon}
            title={epic ? "Nothing open in this epic" : "The backlog is empty"}
            description="New issues land here in To do. Create one with New issue, or ask the agents in Chat to plan a feature."
          />
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            modifiers={[restrictToVerticalAxis]}
            onDragStart={() => (dragging.current = true)}
            onDragCancel={() => (dragging.current = false)}
            onDragEnd={onDragEnd}
          >
            <SortableContext items={visible.map((i) => i.key)} strategy={verticalListSortingStrategy}>
              <Group
                icon={<ListOrderedIcon className="text-muted-foreground size-4" />}
                label={epic ? `Open in ${epic}` : "Open"}
                count={visible.length}
                collapsed={isCollapsed("ranked")}
                onToggle={() => toggle("ranked")}
              >
                {visible.map((issue) => (
                  <Row
                    key={issue.key}
                    issue={issue}
                    members={memberMap}
                    epics={epicMap}
                    onOpen={openIssue}
                    draggable={canEdit}
                    showStatus
                  />
                ))}
              </Group>
            </SortableContext>
          </DndContext>
        )}
      </section>

      <aside className="grid content-start gap-3">
        <h2 className="font-medium">Epics</h2>
        {epics.data?.length === 0 && (
          <p className="text-muted-foreground text-sm">No epics yet. An epic groups the stories of one feature.</p>
        )}
        <ul className="grid gap-2">
          {epics.data?.map((e) => (
            <li key={e.key}>
              <button
                type="button"
                onClick={() => setEpic(epic === e.key ? null : e.key)}
                className={cn(
                  "hover:bg-muted/50 grid w-full gap-2 rounded-lg border p-3 text-left text-sm transition-colors",
                  epic === e.key && "border-primary bg-muted/50",
                )}
              >
                <span className="flex items-center gap-2">
                  <TypeIcon type="epic" />
                  <span className="text-muted-foreground font-mono text-xs">{e.key}</span>
                  <span className="min-w-0 flex-1 truncate font-medium">{e.title}</span>
                </span>
                <Progress value={e.percent} className="h-1.5" />
                <span className="text-muted-foreground text-xs">
                  {e.done} of {e.total} done · {e.percent}%
                </span>
              </button>
            </li>
          ))}
        </ul>
        {epic && (
          <button type="button" className="text-muted-foreground text-left text-xs underline" onClick={() => setEpic(null)}>
            Show all issues
          </button>
        )}
      </aside>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <ListPage />
    </Suspense>
  );
}
