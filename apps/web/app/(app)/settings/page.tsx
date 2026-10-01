"use client";

import { Loader2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useCurrentWorkspace } from "@/lib/queries";

/** Settings live in the workspace: /settings opens yours in the one you were last in. */
export default function SettingsRedirect() {
  const router = useRouter();
  const { workspace } = useCurrentWorkspace();
  useEffect(() => {
    if (workspace) router.replace(`/w/${workspace.slug}/settings/profile`);
  }, [workspace, router]);
  return (
    <div className="flex flex-1 items-center justify-center">
      <Loader2Icon className="text-muted-foreground size-6 animate-spin" />
    </div>
  );
}
