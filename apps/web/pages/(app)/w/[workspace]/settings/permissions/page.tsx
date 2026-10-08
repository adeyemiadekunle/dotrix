import { Skeleton } from "@pmagent/ui/components/skeleton";

import { MemberPermissionsCard } from "@/components/settings/workspace";
import { useCurrentWorkspace } from "@/lib/queries";

/** Settings → What members can do (organisations). Everyone sees it; owners and admins change it. */
export default function Page() {
  const { workspace } = useCurrentWorkspace();
  if (!workspace) return <Skeleton className="h-64" />;
  return <MemberPermissionsCard workspace={workspace} />;
}
