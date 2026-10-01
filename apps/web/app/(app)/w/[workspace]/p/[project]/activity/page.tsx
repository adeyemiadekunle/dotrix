"use client";

import { Suspense } from "react";

import { ActivityView } from "@/components/activity-view";
import { useProjectActivity } from "@/lib/activity";
import { useProjectScope } from "@/lib/queries";

function ActivityPage() {
  const { workspace, scope } = useProjectScope();
  const activity = useProjectActivity(scope);
  return <ActivityView activity={activity} workspace={workspace} intro="What people and agents did in this project." />;
}

export default function Page() {
  return (
    <Suspense>
      <ActivityPage />
    </Suspense>
  );
}
