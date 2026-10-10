import { Button } from "@dotrix/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@dotrix/ui/components/dropdown-menu";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { ArrowUpDownIcon } from "lucide-react";
import { Suspense, useMemo, useState } from "react";

import { BOARD_SORTS, BoardView, type BoardSort } from "@/components/issues/board-view";
import { IssueFilters, useFilters } from "@/components/issues/filters";
import type { EpicMap } from "@/components/issues/issue-card";
import type { MemberMap } from "@/components/issues/meta";
import { NewIssueDialog } from "@/components/issues/new-issue-dialog";
import { useBoard, useEpics, useMembers, useMoveIssue, type IssueStatus } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

function BoardPage() {
  const { workspace, scope, canEdit } = useProjectScope();
  const filters = useFilters();
  const board = useBoard(scope, filters.server);
  const members = useMembers(workspace?.id);
  const move = useMoveIssue(scope);
  const epics = useEpics(scope);
  const [adding, setAdding] = useState<IssueStatus | null>(null);
  const epicMap: EpicMap = useMemo(() => new Map(epics.data?.map((e) => [e.key, e])), [epics.data]);
  const [, openIssue] = useSearchParam("issue");
  const [sortParam, setSort] = useSearchParam("sort");
  const sort: BoardSort = sortParam && sortParam in BOARD_SORTS ? (sortParam as BoardSort) : "rank";
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);
  const labels = useMemo(() => [...new Set(board.data?.columns.flatMap((c) => c.issues.flatMap((i) => i.labels)))].sort(), [board.data]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <IssueFilters
        filters={filters}
        members={members.data ?? []}
        labels={labels}
        scope={scope}
        trailing={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant={sort === "rank" ? "outline" : "secondary"}>
                <ArrowUpDownIcon />
                Sort: {BOARD_SORTS[sort].label}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Order cards by</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={sort} onValueChange={(v) => setSort(v === "rank" ? null : v)}>
                {(Object.keys(BOARD_SORTS) as BoardSort[]).map((id) => (
                  <DropdownMenuRadioItem key={id} value={id}>
                    {BOARD_SORTS[id].label}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
              {canEdit && (
                <>
                  <DropdownMenuSeparator />
                  <p className="text-muted-foreground max-w-56 px-2 py-1.5 text-xs">Drag cards to reorder or move them in Ranked order.</p>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        }
      />
      {board.isLoading ? (
        <div className="flex gap-3 p-4 md:p-6">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-64 w-72 md:flex-1" />
          ))}
        </div>
      ) : (
        <BoardView
          board={board.data}
          members={memberMap}
          epics={epicMap}
          search={filters.search}
          sort={sort}
          canEdit={canEdit}
          onOpen={openIssue}
          onMove={(m) => move.mutate(m)}
          onAdd={canEdit ? setAdding : undefined}
        />
      )}
      {adding && <NewIssueDialog open status={adding} onOpenChange={(open) => !open && setAdding(null)} />}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <BoardPage />
    </Suspense>
  );
}
