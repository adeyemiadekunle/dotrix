"use client";

import { Skeleton } from "@pmagent/ui/components/skeleton";

import { AgentList } from "@/components/agents/agent-list";
import { PageHeader } from "@/components/app-shell";
import { NotFound } from "@/components/states";
import { canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";

/** The workspace's agents: built-in and custom. Everyone sees them; owners and admins change them. */
export default function AgentsPage() {
  const { workspace, notFound } = useCurrentWorkspace();
  if (notFound) return <NotFound what="workspace" />;
  return (
    <>
      <PageHeader title="Agents" parent={workspace?.name} />
      <div className="grid max-w-5xl content-start gap-8 p-4 md:p-8">
        {!workspace ? (
          <Skeleton className="h-64" />
        ) : (
          <AgentList
            scope={{ workspaceId: workspace.id }}
            base={`/w/${workspace.slug}/agents`}
            canEdit={canManageProjects(workspace.role)}
          />
        )}
      </div>
    </>
  );
}
