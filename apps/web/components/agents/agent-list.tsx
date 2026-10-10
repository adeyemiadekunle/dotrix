import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { BotIcon, ChevronRightIcon, PlusIcon } from "lucide-react";
import { Link } from "@/lib/navigation";

import { SOURCE_LABELS, displayName, useAgents, type AgentScope } from "@/lib/agents";

/**
 * The agents of a workspace (or one project): the six built-ins, changed or not, and custom
 * agents. Each opens its editor; owners and admins can add one.
 */
export function AgentList({ scope, base, canEdit }: { scope: AgentScope; base: string; canEdit: boolean }) {
  const agents = useAgents(scope);
  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground text-sm">
          {scope.projectId
            ? "What this project's agents are. A change here applies to this project only; the rest come from the workspace."
            : "Who the agents are in every project of this workspace: their instructions, tools, and what they may change. A project can override them."}
        </p>
        {canEdit && (
          <Button asChild size="sm">
            <Link href={`${base}/new`}>
              <PlusIcon />
              New agent
            </Link>
          </Button>
        )}
      </div>
      {agents.isLoading ? (
        <Skeleton className="h-64" />
      ) : (
        <ul className="bg-card divide-y rounded-xl border">
          {(agents.data ?? []).map((agent) => (
            <li key={agent.handle}>
              <Link
                href={`${base}/${agent.handle}`}
                className="hover:bg-muted/60 flex items-center gap-3 px-4 py-3 first:rounded-t-xl last:rounded-b-xl"
              >
                <span className="bg-muted flex size-8 shrink-0 items-center justify-center rounded-lg">
                  <BotIcon className="size-4" />
                </span>
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    {displayName(agent)}
                    <span className="text-muted-foreground font-mono text-xs font-normal">@{agent.handle}</span>
                    <Badge variant={agent.source === "built_in" ? "outline" : "secondary"}>
                      {SOURCE_LABELS[agent.source]}
                      {agent.scope === "project" && " for this project"}
                    </Badge>
                  </span>
                  <span className="text-muted-foreground truncate text-xs">{agent.description || agent.name}</span>
                </span>
                <ChevronRightIcon className="text-muted-foreground size-4" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
