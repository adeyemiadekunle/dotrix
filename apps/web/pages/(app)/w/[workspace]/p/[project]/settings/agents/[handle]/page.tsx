import { Skeleton } from "@dotrix/ui/components/skeleton";
import { useParams } from "@/lib/navigation";

import { AgentEditor } from "@/components/agents/agent-editor";
import { canManageProjects } from "@/lib/labels";
import { useProjectScope } from "@/lib/queries";

/** One agent as this project uses it; saving makes this project's own version. */
export default function ProjectAgentPage() {
  const { handle } = useParams<{ handle: string }>();
  const { workspace, project, scope } = useProjectScope();
  if (!workspace || !project || !scope) return <Skeleton className="m-4 h-96 max-w-5xl md:m-8" />;
  return (
    <div className="p-4 md:p-8">
      <AgentEditor
        scope={scope}
        handle={handle}
        base={`/w/${workspace.slug}/p/${project.key}/settings/agents`}
        canEdit={canManageProjects(workspace.role)}
        isOwner={workspace.role === "owner"}
      />
    </div>
  );
}
