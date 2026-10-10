import { Suspense } from "react";

import { ActivityView } from "@/components/activity-view";
import { PageHeader } from "@/components/app-shell";
import { NotFound } from "@/components/states";
import { useWorkspaceActivity } from "@/lib/activity";
import { useCurrentWorkspace } from "@/lib/queries";

/** What people and agents did across the workspace's projects (the audit log stays in Settings). */
function WorkspaceActivity() {
  const { workspace, notFound } = useCurrentWorkspace();
  const activity = useWorkspaceActivity(workspace && workspace.role !== "guest" ? workspace.id : undefined);
  if (notFound) return <NotFound what="workspace" />;
  return (
    <>
      <PageHeader title="Activity" parent={workspace?.name} />
      <ActivityView activity={activity} workspace={workspace} intro="What people and agents did in the projects you can see." showProject />
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <WorkspaceActivity />
    </Suspense>
  );
}
