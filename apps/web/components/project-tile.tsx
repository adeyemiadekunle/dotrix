import { cn } from "@pmagent/ui/lib/utils";

// Strong enough for white text in both themes.
const COLOURS = [
  "bg-teal-600",
  "bg-violet-600",
  "bg-sky-600",
  "bg-amber-600",
  "bg-rose-600",
  "bg-emerald-600",
  "bg-indigo-600",
  "bg-orange-600",
];

/** A project's small coloured square with its key's first letter; the colour follows the key. */
export function ProjectTile({ projectKey, className }: { projectKey: string; className?: string }) {
  let hash = 0;
  for (const ch of projectKey) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex size-5 shrink-0 items-center justify-center rounded-[5px] text-[11px] font-semibold text-white",
        COLOURS[hash % COLOURS.length],
        className,
      )}
    >
      {projectKey.charAt(0)}
    </span>
  );
}
