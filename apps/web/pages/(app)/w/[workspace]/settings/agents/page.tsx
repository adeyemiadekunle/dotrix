import { Skeleton } from "@pmagent/ui/components/skeleton";

import { AgentList } from "@/components/agents/agent-list";
import { WorkspaceRules } from "@/components/agents/workspace-rules";
import { WorkspaceSkills } from "@/components/agents/workspace-skills";
import { canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";

/** Settings → Agents: the workspace's built-in and custom agents (owners and admins). */
export default function AgentsPage() {
  const { workspace } = useCurrentWorkspace();
  if (!workspace) return <Skeleton className="h-64" />;
  if (!canManageProjects(workspace.role)) {
    return <p className="text-muted-foreground text-sm">Only owners and admins manage the agents.</p>;
  }
  return (
    <div className="grid gap-10">
      <section className="grid gap-3">
        <h2 className="font-semibold">Agents</h2>
        <AgentList scope={{ workspaceId: workspace.id }} base={`/w/${workspace.slug}/settings/agents`} canEdit />
      </section>
      <WorkspaceRules workspaceId={workspace.id} />
      <div className="@container">
        <WorkspaceSkills workspaceId={workspace.id} />
      </div>
    </div>
  );
}
