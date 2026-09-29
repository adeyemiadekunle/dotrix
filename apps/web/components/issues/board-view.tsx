"use client";

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  rectIntersection,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  type KeyboardCoordinateGetter,
} from "@dnd-kit/core";
import { SortableContext, arrayMove, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { cn } from "@pmagent/ui/lib/utils";
import { ChevronDownIcon, ChevronRightIcon, PlusIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Board, IssueStatus, IssueSummary, RankTarget } from "@/lib/issues";

import { IssueCard, SortableIssueCard, type EpicMap } from "./issue-card";
import { STATUSES, STATUS_META, StatusIcon, type MemberMap } from "./meta";

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
  epics,
  onOpen,
  canEdit,
  collapsed,
  onToggle,
  onAdd,
}: {
  status: IssueStatus;
  issues: IssueSummary[];
  members: MemberMap;
  epics: EpicMap;
  onOpen: (key: string) => void;
  canEdit: boolean;
  collapsed: boolean;
  onToggle: () => void;
  onAdd?: () => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `${COLUMN_ID}${status}` });
  const meta = STATUS_META[status];
  return (
    // Stacked full width when the board is narrow; side by side (scrolling, 15rem each) when
    // there's room for a few; sharing the width once all five fit at about 13rem (64rem). Sized by
    // the board's own width (container queries), so the chat panel narrowing it works like a smaller screen.
    <section className="bg-muted/70 dark:bg-muted/40 flex w-full flex-col rounded-xl @2xl:w-60 @2xl:shrink-0 @5xl:w-auto @5xl:min-w-0 @5xl:flex-1">
      <header className="flex h-10 items-center gap-2 px-3 text-sm">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-label={`${collapsed ? "Show" : "Hide"} ${meta.label}`}
          className="text-muted-foreground hover:text-foreground -ml-1 flex size-8 items-center justify-center @2xl:hidden"
        >
          {collapsed ? <ChevronRightIcon className="size-4" /> : <ChevronDownIcon className="size-4" />}
        </button>
        <StatusIcon status={status} />
        <span className="truncate font-semibold whitespace-nowrap">{meta.label}</span>
        <span className="text-muted-foreground text-xs tabular-nums">{issues.length}</span>
        {onAdd && (
          <button
            type="button"
            onClick={onAdd}
            aria-label={`Add to ${meta.label}`}
            title={`Add an issue to ${meta.label}`}
            className="text-muted-foreground hover:bg-background hover:text-foreground -mr-1.5 ml-auto flex size-7 items-center justify-center rounded-md transition-colors"
          >
            <PlusIcon className="size-4" />
          </button>
        )}
      </header>
      <SortableContext items={issues.map((i) => i.key)} strategy={verticalListSortingStrategy}>
        <div
          ref={setNodeRef}
          className={cn(
            "flex flex-col gap-2 rounded-b-xl p-2 pt-0 transition-colors @2xl:min-h-24 @2xl:flex-1",
            collapsed && "hidden @2xl:flex",
            isOver && "bg-primary/5 ring-primary/30 ring-1 ring-inset",
          )}
        >
          {issues.map((issue) => (
            <SortableIssueCard
              key={issue.key}
              issue={issue}
              members={members}
              epics={epics}
              onOpen={onOpen}
              disabled={!canEdit}
            />
          ))}
          {issues.length === 0 && (
            <p className="text-muted-foreground border-foreground/15 rounded-lg border border-dashed p-2 text-center text-xs @2xl:p-4">
              {canEdit ? "Drop issues here" : "Nothing here"}
            </p>
          )}
        </div>
      </SortableContext>
    </section>
  );
}

/**
 * Keyboard dragging: up and down move within the column (dnd-kit's sortable behaviour); left and
 * right move the card to the top of the previous or next column, the way a pointer drag between
 * columns does. Space picks a card up and drops it, Escape cancels.
 */
function betweenColumns(columnsRef: { current: Columns }): KeyboardCoordinateGetter {
  return (event, args) => {
    const step = event.code === "ArrowRight" ? 1 : event.code === "ArrowLeft" ? -1 : 0;
    if (step === 0) return sortableKeyboardCoordinates(event, args);
    const { active, droppableRects } = args.context;
    const from = active ? findColumn(columnsRef.current, String(active.id)) : undefined;
    const to = from && STATUSES[STATUSES.indexOf(from) + step];
    if (!to) return undefined;
    event.preventDefault();
    // Aim at the target column's first card (so it lands on top), or the empty column itself.
    const first = columnsRef.current[to].find((i) => i.key !== active?.id);
    const rect = (first && droppableRects.get(first.key)) ?? droppableRects.get(`${COLUMN_ID}${to}`);
    return rect ? { x: rect.left + 1, y: rect.top + 1 } : undefined;
  };
}

/**
 * Columns by status, each in backlog (rank) order. Dragging a card to another column changes its
 * status; dropping it between cards ranks it next to them.
 */
export function BoardView({
  board,
  members,
  epics,
  search,
  canEdit,
  onOpen,
  onMove,
  onAdd,
}: {
  board: Board | undefined;
  members: MemberMap;
  epics: EpicMap;
  search: string;
  canEdit: boolean;
  onOpen: (key: string) => void;
  onMove: (move: { key: string; status?: IssueStatus; rank?: RankTarget }) => void;
  /** Start a new issue in a column; only people move work to Done, so that column has none. */
  onAdd?: (status: IssueStatus) => void;
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

  // The keyboard's coordinate getter and the drag handlers read the columns and the dragged card
  // from refs, updated as they change: keys pressed in quick succession (Space, an arrow, Space)
  // can arrive before React re-renders, and state from the last render would miss the move.
  const columnsRef = useRef(columns);
  useEffect(() => {
    columnsRef.current = columns;
  }, [columns]);
  const activeRef = useRef<{ issue: IssueSummary; from: IssueStatus } | null>(null);
  function updateColumns(next: Columns) {
    columnsRef.current = next;
    setColumns(next);
  }
  const sensors = useSensors(
    // A small distance, so a click still opens the issue.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: useMemo(() => betweenColumns(columnsRef), []) }),
  );

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return columns;
    const match = (i: IssueSummary) => i.title.toLowerCase().includes(q) || i.key.toLowerCase().includes(q);
    return Object.fromEntries(STATUSES.map((s) => [s, columns[s].filter(match)])) as Columns;
  }, [columns, search]);

  // Pointer drags find the nearest spot by corners; a keyboard move places the card squarely
  // on its target, where corners can still favour the card's old spot next to a tall empty
  // column, so keyboard drags go by overlap first.
  const byKeyboard = useRef(false);
  const collisionDetection: CollisionDetection = (args) => {
    if (!byKeyboard.current) return closestCorners(args);
    const overlapping = rectIntersection(args);
    return overlapping.length ? overlapping : closestCorners(args);
  };

  function onDragStart({ active: a, activatorEvent }: DragStartEvent) {
    byKeyboard.current = activatorEvent instanceof KeyboardEvent;
    const columns = columnsRef.current;
    const from = findColumn(columns, String(a.id));
    const issue = from && columns[from].find((i) => i.key === a.id);
    if (from && issue) {
      dragging.current = true;
      activeRef.current = { issue, from };
      setActive(activeRef.current);
    }
  }

  function onDragOver({ active: a, over }: DragOverEvent) {
    if (!over) return;
    const prev = columnsRef.current;
    const from = findColumn(prev, String(a.id));
    const to = findColumn(prev, String(over.id));
    if (!from || !to || from === to) return;
    const moving = prev[from].find((i) => i.key === a.id);
    if (!moving) return;
    const target = prev[to];
    const overIndex = target.findIndex((i) => i.key === over.id);
    const index = overIndex >= 0 ? overIndex : target.length;
    updateColumns({
      ...prev,
      [from]: prev[from].filter((i) => i.key !== a.id),
      [to]: [...target.slice(0, index), { ...moving, status: to }, ...target.slice(index)],
    });
  }

  function onDragEnd({ active: a, over }: DragEndEvent) {
    const started = activeRef.current;
    activeRef.current = null;
    dragging.current = false;
    setActive(null);
    if (!over || !started) return;
    const key = String(a.id);
    const columns = columnsRef.current;
    const column = findColumn(columns, key);
    if (!column) return;
    let list = columns[column];
    const oldIndex = list.findIndex((i) => i.key === key);
    const overIndex = list.findIndex((i) => i.key === over.id);
    if (overIndex >= 0 && overIndex !== oldIndex) {
      list = arrayMove(list, oldIndex, overIndex);
      updateColumns({ ...columns, [column]: list });
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
      collisionDetection={collisionDetection}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        activeRef.current = null;
        dragging.current = false;
        setActive(null);
        updateColumns(toColumns(board));
      }}
    >
      <div className="@container flex min-w-0 flex-1">
        <div className="flex flex-1 flex-col gap-3 px-4 pt-3 pb-4 md:px-6 md:pb-6 @2xl:flex-row @2xl:overflow-x-auto">
          {STATUSES.map((status) => (
            <Column
              key={status}
              status={status}
              issues={visible[status]}
              members={members}
              epics={epics}
              onOpen={onOpen}
              canEdit={canEdit && !search}
              collapsed={collapsed.has(status)}
              onAdd={onAdd && status !== "done" ? () => onAdd(status) : undefined}
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
      <DragOverlay>{active && <IssueCard issue={active.issue} members={members} epics={epics} dragging />}</DragOverlay>
    </DndContext>
  );
}
