import { cn } from "@pmagent/ui/lib/utils";

export function Logo({ className, withName = true }: { className?: string; withName?: boolean }) {
  return (
    <span className={cn("flex items-center gap-2 font-medium", className)}>
      <span className="bg-brand text-brand-foreground flex size-7 items-center justify-center rounded-md text-xs font-semibold">
        pm
      </span>
      {withName && <span>pmagent</span>}
    </span>
  );
}
