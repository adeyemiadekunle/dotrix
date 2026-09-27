"use client";

import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Suspense, useMemo } from "react";

import { BoardView } from "@/components/issues/board-view";
import { IssueFilters, useFilters } from "@/components/issues/filters";
import type { MemberMap } from "@/components/issues/meta";
import { useBoard, useMembers, useMoveIssue } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

function BoardPage() {
  const { workspace, scope, canEdit } = useProjectScope();
  const filters = useFilters();
  const board = useBoard(scope, filters.server);
  const members = useMembers(workspace?.id);
  const move = useMoveIssue(scope);
  const [, openIssue] = useSearchParam("issue");
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);
  const labels = useMemo(
    () => [...new Set(board.data?.columns.flatMap((c) => c.issues.flatMap((i) => i.labels)))].sort(),
    [board.data],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <IssueFilters filters={filters} members={members.data ?? []} labels={labels} scope={scope} />
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
          search={filters.search}
          canEdit={canEdit}
          onOpen={openIssue}
          onMove={(m) => move.mutate(m)}
        />
      )}
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
