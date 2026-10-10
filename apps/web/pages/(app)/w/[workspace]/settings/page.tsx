import { Skeleton } from "@dotrix/ui/components/skeleton";

import { GeneralCard } from "@/components/settings/workspace";
import { useCurrentWorkspace } from "@/lib/queries";

/** Settings → General: the workspace's name and kind. */
export default function Page() {
  const { workspace } = useCurrentWorkspace();
  if (!workspace) return <Skeleton className="h-64" />;
  return <GeneralCard key={workspace.id} workspace={workspace} />;
}
