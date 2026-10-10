import type { Schemas } from "@dotrix/api-client";
import { cn } from "@dotrix/ui/lib/utils";

export type ProjectHealth = Schemas["ProjectHealth"];

export const HEALTH_LABELS: Record<ProjectHealth, string> = {
  on_track: "On track",
  at_risk: "At risk",
  off_track: "Off track",
};

const HEALTH_STYLES: Record<ProjectHealth, string> = {
  on_track: "bg-brand-muted text-brand-muted-foreground",
  at_risk: "bg-warning-muted text-warning-foreground",
  off_track: "bg-destructive/10 text-destructive",
};

/** How the project is going, as its owners and admins say. */
export function HealthBadge({ health, className }: { health: ProjectHealth; className?: string }) {
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", HEALTH_STYLES[health], className)}>{HEALTH_LABELS[health]}</span>
  );
}

const dateFormat = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" });

/** "1 Dec 2026" from an ISO date (read as a calendar date, not a moment in time). */
export function formatDay(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return dateFormat.format(new Date(y, m - 1, d));
}
