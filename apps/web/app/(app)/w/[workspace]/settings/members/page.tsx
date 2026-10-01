"use client";

import { Skeleton } from "@pmagent/ui/components/skeleton";

import { MembersCard } from "@/components/settings/members";
import { useCurrentWorkspace } from "@/lib/queries";

/** Settings → Members: everyone sees the people; owners and admins manage them. */
export default function Page() {
  const { workspace } = useCurrentWorkspace();
  if (!workspace) return <Skeleton className="h-64" />;
  return <MembersCard workspace={workspace} />;
}
