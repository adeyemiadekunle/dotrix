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
import { Badge } from "@pmagent/ui/components/badge";
import { Progress } from "@pmagent/ui/components/progress";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { GripVerticalIcon, ListTodoIcon } from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { AssigneeAvatar, PriorityIcon, StatusBadge, TypeIcon, type MemberMap } from "@/components/issues/meta";
import { EmptyState } from "@/components/states";
import { useBacklog, useEpics, useMembers, useMoveIssue, type IssueSummary } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

function Row({
  issue,
  members,
  onOpen,
  draggable,
}: {
  issue: IssueSummary;
  members: MemberMap;
  onOpen: (key: string) => void;
  draggable: boolean;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: issue.key,
    disabled: !draggable,
  });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        "bg-card hover:bg-muted/50 flex items-center gap-3 px-3 py-2 text-sm",
        isDragging && "relative z-10 shadow-lg",
      )}
    >
      {draggable && (
        <button
          ref={setActivatorNodeRef}
          type="button"
          aria-label={`Reorder ${issue.key}`}
          className="text-muted-foreground hover:text-foreground cursor-grab touch-none active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVerticalIcon className="size-4" />
        </button>
      )}
      <button type="button" className="flex min-w-0 flex-1 items-center gap-3 text-left" onClick={() => onOpen(issue.key)}>
        <TypeIcon type={issue.type} />
        <span className="text-muted-foreground w-16 shrink-0 font-mono text-xs">{issue.key}</span>
        <span className="min-w-0 flex-1 truncate">{issue.title}</span>
        {issue.parent_key && (
          <Badge variant="outline" className="hidden font-mono text-[10px] sm:inline-flex">
            {issue.parent_key}
          </Badge>
        )}
        <StatusBadge status={issue.status} className="hidden sm:inline-flex" />
        {issue.estimate != null && (
          <span className="bg-muted hidden rounded px-1.5 text-xs tabular-nums sm:inline">{issue.estimate}</span>
        )}
      </button>
      <PriorityIcon priority={issue.priority} />
      <AssigneeAvatar issue={issue} members={members} />
    </li>
  );
}

function BacklogPage() {
  const { workspace, scope, canEdit } = useProjectScope();
  const backlog = useBacklog(scope);
  const epics = useEpics(scope);
  const members = useMembers(workspace?.id);
  const move = useMoveIssue(scope);
  const [, openIssue] = useSearchParam("issue");
  const [epic, setEpic] = useSearchParam("epic");
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);

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
        <div className="flex items-center gap-2">
          <h2 className="font-medium">Backlog</h2>
          <span className="text-muted-foreground text-sm">
            {visible.length} open{epic ? ` in ${epic}` : ""} · highest first, drag to reorder
          </span>
        </div>
        {backlog.isLoading ? (
          <Skeleton className="h-64" />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={ListTodoIcon}
            title={epic ? "Nothing open in this epic" : "The backlog is empty"}
            description="New issues land here in To do. Create one with New issue, or ask the PM agent to plan a feature."
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
              <ul className="divide-y overflow-hidden rounded-lg border">
                {visible.map((issue) => (
                  <Row key={issue.key} issue={issue} members={memberMap} onOpen={openIssue} draggable={canEdit} />
                ))}
              </ul>
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
      <BacklogPage />
    </Suspense>
  );
}
