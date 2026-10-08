import { cn } from "@pmagent/ui/lib/utils";
import type { CSSProperties } from "react";

import { PROJECT_ICONS, projectColor } from "@/lib/project-look";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

/**
 * A project's small tile: its icon (or its key's first letter) in its colour, on a tint of it.
 * Callers usually know only the key; the icon and colour come from the cached project list.
 */
export function ProjectTile({ projectKey, className }: { projectKey: string; className?: string }) {
  const { workspace } = useCurrentWorkspace();
  const project = useProjects(workspace?.id).data?.find((p) => p.key === projectKey);
  const Icon = project?.icon ? PROJECT_ICONS[project.icon] : undefined;
  const color = projectColor(projectKey, project?.color);
  return (
    <span
      aria-hidden
      style={{ "--tile": color } as CSSProperties}
      className={cn(
        "inline-flex size-5 shrink-0 items-center justify-center rounded-[5px] text-[11px] font-semibold",
        "bg-[color-mix(in_srgb,var(--tile)_16%,transparent)] text-[color-mix(in_srgb,var(--tile)_100%,var(--foreground))]",
        "dark:text-[color-mix(in_srgb,var(--tile)_72%,var(--foreground))]",
        className,
      )}
    >
      {Icon ? <Icon className="size-[65%]" /> : projectKey.charAt(0)}
    </span>
  );
}
