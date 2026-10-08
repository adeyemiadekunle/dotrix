import { Skeleton } from "@pmagent/ui/components/skeleton";

import { InvitesCard } from "@/components/settings/invites";
import { canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";

/** Settings → Invites (organisations; owners and admins). */
export default function Page() {
  const { workspace } = useCurrentWorkspace();
  if (!workspace) return <Skeleton className="h-64" />;
  return canManageProjects(workspace.role) ? (
    <InvitesCard workspace={workspace} />
  ) : (
    <p className="text-muted-foreground text-sm">Only owners and admins invite people.</p>
  );
}
