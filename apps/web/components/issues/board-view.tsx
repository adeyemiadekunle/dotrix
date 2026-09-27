"use client";

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { cn } from "@pmagent/ui/lib/utils";
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Board, IssueStatus, IssueSummary, RankTarget } from "@/lib/issues";

import { IssueCard, SortableIssueCard } from "./issue-card";
import { STATUSES, STATUS_META, type MemberMap } from "./meta";

type Columns = Record<IssueStatus, IssueSummary[]>;

function toColumns(board: Board | undefined): Columns {
  const columns = Object.fromEntries(STATUSES.map((s) => [s, [] as IssueSummary[]])) as Columns;
  for (const column of board?.columns ?? []) columns[column.status] = column.issues;
  return columns;
}

const COLUMN_ID = "column:";

function findColumn(columns: Columns, id: string): IssueStatus | undefined {
  if (id.startsWith(COLUMN_ID)) return id.slice(COLUMN_ID.length) as IssueStatus;
  return STATUSES.find((s) => columns[s].some((i) => i.key === id));
}

function Column({
  status,
  issues,
  members,
  onOpen,
  canEdit,
  collapsed,
  onToggle,
}: {
  status: IssueStatus;
  issues: IssueSummary[];
  members: MemberMap;
  onOpen: (key: string) => void;
  canEdit: boolean;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `${COLUMN_ID}${status}` });
  const meta = STATUS_META[status];
  return (
    // Stacked full width when the board is narrow; side by side (scrolling, 16rem each) when
    // there's room for a few; sharing the width only when all five fit at that size (80rem). Sized by the board's own
    // width (container queries), so the chat panel narrowing it works like a smaller screen.
    <section className="bg-muted/40 flex w-full flex-col rounded-xl border @2xl:w-64 @2xl:shrink-0 @7xl:w-auto @7xl:min-w-0 @7xl:flex-1">
      <header className="flex items-center gap-2 px-3 py-2.5 text-sm font-medium">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-label={`${collapsed ? "Show" : "Hide"} ${meta.label}`}
          className="text-muted-foreground hover:text-foreground -ml-1 @2xl:hidden"
        >
          {collapsed ? <ChevronRightIcon className="size-4" /> : <ChevronDownIcon className="size-4" />}
        </button>
        <span className={cn("size-2 shrink-0 rounded-full", meta.dot)} />
        <span className="truncate whitespace-nowrap">{meta.label}</span>
        <span className="text-muted-foreground tabular-nums">{issues.length}</span>
      </header>
      <SortableContext items={issues.map((i) => i.key)} strategy={verticalListSortingStrategy}>
        <div
          ref={setNodeRef}
          className={cn(
            "flex flex-col gap-2 p-2 pt-0 @2xl:min-h-24 @2xl:flex-1",
            collapsed && "hidden @2xl:flex",
            isOver && "bg-muted/60 rounded-b-xl",
          )}
        >
          {issues.map((issue) => (
            <SortableIssueCard key={issue.key} issue={issue} members={members} onOpen={onOpen} disabled={!canEdit} />
          ))}
          {issues.length === 0 && (
            <p className="text-muted-foreground rounded-lg border border-dashed p-2 text-center text-xs @2xl:p-4">
              {canEdit ? "Drop issues here" : "Nothing here"}
            </p>
          )}
        </div>
      </SortableContext>
    </section>
  );
}

/**
 * Columns by status, each in backlog (rank) order. Dragging a card to another column changes its
 * status; dropping it between cards ranks it next to them.
 */
export function BoardView({
  board,
  members,
  search,
  canEdit,
  onOpen,
  onMove,
}: {
  board: Board | undefined;
  members: MemberMap;
  search: string;
  canEdit: boolean;
  onOpen: (key: string) => void;
  onMove: (move: { key: string; status?: IssueStatus; rank?: RankTarget }) => void;
}) {
  const [columns, setColumns] = useState<Columns>(() => toColumns(board));
  const [active, setActive] = useState<{ issue: IssueSummary; from: IssueStatus } | null>(null);
  // Stacked (narrow) layout only: finished work starts folded away.
  const [collapsed, setCollapsed] = useState<Set<IssueStatus>>(() => new Set(["done"]));

  // Follow the server whenever it sends a new board, except mid-drag. After a drop the local
  // order stays on screen until the refetch replaces it (or puts it back if the move failed).
  const dragging = useRef(false);
  useEffect(() => {
    if (!dragging.current) setColumns(toColumns(board));
  }, [board]);

  const sensors = useSensors(
    // A small distance, so a click still opens the issue.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return columns;
    const match = (i: IssueSummary) => i.title.toLowerCase().includes(q) || i.key.toLowerCase().includes(q);
    return Object.fromEntries(STATUSES.map((s) => [s, columns[s].filter(match)])) as Columns;
  }, [columns, search]);

  function onDragStart({ active: a }: DragStartEvent) {
    const from = findColumn(columns, String(a.id));
    const issue = from && columns[from].find((i) => i.key === a.id);
    if (from && issue) {
      dragging.current = true;
      setActive({ issue, from });
    }
  }

  function onDragOver({ active: a, over }: DragOverEvent) {
    if (!over) return;
    const from = findColumn(columns, String(a.id));
    const to = findColumn(columns, String(over.id));
    if (!from || !to || from === to) return;
    setColumns((prev) => {
      const moving = prev[from].find((i) => i.key === a.id);
      if (!moving) return prev;
      const target = prev[to];
      const overIndex = target.findIndex((i) => i.key === over.id);
      const index = overIndex >= 0 ? overIndex : target.length;
      return {
        ...prev,
        [from]: prev[from].filter((i) => i.key !== a.id),
        [to]: [...target.slice(0, index), { ...moving, status: to }, ...target.slice(index)],
      };
    });
  }

  function onDragEnd({ active: a, over }: DragEndEvent) {
    const started = active;
    dragging.current = false;
    setActive(null);
    if (!over || !started) return;
    const key = String(a.id);
    const column = findColumn(columns, key);
    if (!column) return;
    let list = columns[column];
    const oldIndex = list.findIndex((i) => i.key === key);
    const overIndex = list.findIndex((i) => i.key === over.id);
    if (overIndex >= 0 && overIndex !== oldIndex) {
      list = arrayMove(list, oldIndex, overIndex);
      setColumns((prev) => ({ ...prev, [column]: list }));
    }
    const index = list.findIndex((i) => i.key === key);
    const next = list[index + 1];
    const prev = list[index - 1];
    const originalIndex = toColumns(board)[started.from].findIndex((i) => i.key === key);
    const statusChanged = column !== started.from;
    if (!statusChanged && index === originalIndex) return;
    onMove({
      key,
      status: statusChanged ? column : undefined,
      rank: next ? { before: next.key } : prev ? { after: prev.key } : undefined,
    });
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        dragging.current = false;
        setActive(null);
        setColumns(toColumns(board));
      }}
    >
      <div className="@container flex min-w-0 flex-1">
        <div className="flex flex-1 flex-col gap-3 p-4 md:p-6 @2xl:flex-row @2xl:overflow-x-auto">
          {STATUSES.map((status) => (
            <Column
              key={status}
              status={status}
              issues={visible[status]}
              members={members}
              onOpen={onOpen}
              canEdit={canEdit && !search}
              collapsed={collapsed.has(status)}
              onToggle={() =>
                setCollapsed((prev) => {
                  const next = new Set(prev);
                  if (next.has(status)) next.delete(status);
                  else next.add(status);
                  return next;
                })
              }
            />
          ))}
        </div>
      </div>
      <DragOverlay>{active && <IssueCard issue={active.issue} members={members} dragging />}</DragOverlay>
    </DndContext>
  );
}
