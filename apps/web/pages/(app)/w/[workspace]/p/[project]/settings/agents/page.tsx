import { Skeleton } from "@pmagent/ui/components/skeleton";

import { AgentList } from "@/components/agents/agent-list";
import { canManageProjects } from "@/lib/labels";
import { useProjectScope } from "@/lib/queries";

/** The agents this project's runs use: its own versions, else the workspace's, else the built-ins. */
export default function ProjectAgentsPage() {
  const { workspace, project, scope } = useProjectScope();
  if (!workspace || !project || !scope) return <Skeleton className="m-4 h-64 max-w-5xl md:m-8" />;
  return (
    <div className="grid max-w-5xl content-start gap-4 p-4 md:p-8">
      <h1 className="text-lg font-semibold">Agents for {project.name}</h1>
      <AgentList
        scope={scope}
        base={`/w/${workspace.slug}/p/${project.key}/settings/agents`}
        canEdit={canManageProjects(workspace.role)}
      />
    </div>
  );
}
