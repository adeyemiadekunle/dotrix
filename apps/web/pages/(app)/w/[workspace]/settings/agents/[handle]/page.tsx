import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useParams } from "@/lib/navigation";

import { AgentEditor } from "@/components/agents/agent-editor";
import { canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";

/** One of the workspace's agents, or a new one (settings/agents/new). Owners and admins. */
export default function AgentPage() {
  const { handle } = useParams<{ handle: string }>();
  const { workspace } = useCurrentWorkspace();
  if (!workspace) return <Skeleton className="h-96" />;
  if (!canManageProjects(workspace.role)) {
    return <p className="text-muted-foreground text-sm">Only owners and admins manage the agents.</p>;
  }
  return (
    <AgentEditor
      scope={{ workspaceId: workspace.id }}
      handle={handle}
      base={`/w/${workspace.slug}/settings/agents`}
      canEdit
      isOwner={workspace.role === "owner"}
    />
  );
}
