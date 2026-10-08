import { Loader2Icon } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useEffect } from "react";

import { useCurrentWorkspace } from "@/lib/queries";

/** "/" opens the workspace you were last in (or your first one). */
export default function Home() {
  const router = useRouter();
  const { workspace } = useCurrentWorkspace();
  useEffect(() => {
    if (workspace) router.replace(`/w/${workspace.slug}`);
  }, [workspace, router]);
  return (
    <div className="flex flex-1 items-center justify-center">
      <Loader2Icon className="text-muted-foreground size-6 animate-spin" />
    </div>
  );
}
