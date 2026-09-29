"use client";

import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useParams } from "next/navigation";

import { AgentEditor } from "@/components/agents/agent-editor";
import { PageHeader } from "@/components/app-shell";
import { NotFound } from "@/components/states";
import { canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";

/** One of the workspace's agents, or a new one (/agents/new). */
export default function AgentPage() {
  const { handle } = useParams<{ handle: string }>();
  const { workspace, notFound } = useCurrentWorkspace();
  if (notFound) return <NotFound what="workspace" />;
  return (
    <>
      <PageHeader title={handle === "new" ? "New agent" : `@${handle}`} parent="Agents" />
      <div className="p-4 md:p-8">
        {!workspace ? (
          <Skeleton className="h-96 max-w-5xl" />
        ) : (
          <AgentEditor
            scope={{ workspaceId: workspace.id }}
            handle={handle}
            base={`/w/${workspace.slug}/agents`}
            canEdit={canManageProjects(workspace.role)}
            isOwner={workspace.role === "owner"}
          />
        )}
      </div>
    </>
  );
}
