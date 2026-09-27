"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { ShieldCheckIcon } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { RunApprovals } from "@/components/agent/approvals";
import { PageHeader } from "@/components/app-shell";
import { timeAgo } from "@/components/issues/issue-activity";
import { EmptyState, NotFound } from "@/components/states";
import { runTitle, useWorkspaceApprovals, type Run, type WorkspaceApproval } from "@/lib/agent";
import { useMembers } from "@/lib/issues";
import { useCurrentWorkspace } from "@/lib/queries";

interface Group {
  runId: string;
  projectId: string;
  projectKey: string;
  projectName: string;
  message: string;
  requestedBy: string | null;
  createdAt: string;
  approvals: WorkspaceApproval[];
}

/** Everything the agents are waiting on in this workspace, one card per instruction. */
export default function ApprovalsPage() {
  const { workspace, notFound } = useCurrentWorkspace();
  const canDecide = Boolean(workspace && workspace.role !== "guest");
  const approvals = useWorkspaceApprovals(workspace?.id, canDecide);
  const members = useMembers(workspace?.id);
  const names = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m.display_name])), [members.data]);

  const groups = useMemo(() => {
    const byRun = new Map<string, Group>();
    for (const a of approvals.data ?? []) {
      const group = byRun.get(a.run_id) ?? {
        runId: a.run_id,
        projectId: a.project_id,
        projectKey: a.project_key,
        projectName: a.project_name,
        message: runTitle({ kind: "chat", message: a.run_message }),
        requestedBy: a.requested_by_id,
        createdAt: a.created_at,
        approvals: [],
      };
      group.approvals.push(a);
      byRun.set(a.run_id, group);
    }
    return [...byRun.values()];
  }, [approvals.data]);

  if (notFound) return <NotFound what="workspace" />;
  return (
    <>
      <PageHeader title="Approvals" parent={workspace?.name} />
      <div className="grid max-w-3xl content-start gap-4 p-4 md:p-6">
        <p className="text-muted-foreground text-sm">
          Changes the agents want to make, across every project. Nothing is written until someone decides.
        </p>
        {!canDecide && workspace && <p className="text-sm">Guests don&apos;t approve changes.</p>}
        {approvals.isLoading && <Skeleton className="h-40" />}
        {approvals.data?.length === 0 && (
          <EmptyState
            icon={ShieldCheckIcon}
            title="Nothing waiting"
            description="When an agent wants to change a document or the board, it shows up here and in the chat."
          />
        )}
        {workspace &&
          groups.map((g) => {
            // The approvals card works on a run; build the part of one it needs.
            const run = { id: g.runId, approvals: g.approvals } as unknown as Run;
            return (
              <Card key={g.runId}>
                <CardHeader>
                  <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
                    <Badge variant="outline" className="font-mono">
                      {g.projectKey}
                    </Badge>
                    <Link href={`/w/${workspace.slug}/p/${g.projectKey}/board`} className="hover:underline">
                      {g.projectName}
                    </Link>
                  </CardTitle>
                  <CardDescription>
                    <span className="text-foreground">&ldquo;{g.message}&rdquo;</span>
                    <br />
                    {g.requestedBy ? `${names.get(g.requestedBy) ?? "Someone"} asked` : "Asked"} {timeAgo(g.createdAt)}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <RunApprovals
                    run={run}
                    scope={{ workspaceId: workspace.id, projectId: g.projectId }}
                    canDecide={canDecide}
                  />
                </CardContent>
              </Card>
            );
          })}
      </div>
    </>
  );
}
