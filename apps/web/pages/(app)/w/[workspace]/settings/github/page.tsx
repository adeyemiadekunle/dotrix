import { Skeleton } from "@pmagent/ui/components/skeleton";

import { GitHubSettings } from "@/components/settings/github";
import { canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";

/** Settings → GitHub: the GitHub App's installations this workspace uses (owners and admins). */
export default function Page() {
  const { workspace } = useCurrentWorkspace();
  if (!workspace) return <Skeleton className="h-64" />;
  if (!canManageProjects(workspace.role)) {
    return <p className="text-muted-foreground text-sm">Only owners and admins connect GitHub.</p>;
  }
  return <GitHubSettings workspace={workspace} />;
}
