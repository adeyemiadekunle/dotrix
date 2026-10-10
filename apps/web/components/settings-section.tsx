import { cn } from "@dotrix/ui/lib/utils";
import type { ComponentProps } from "react";

// A settings page is a column of sections: what the section is on the left, its controls on the
// right (stacked when the section itself is narrow, e.g. beside the settings nav on a laptop).
// The parts mirror Card's, so a card converts by renaming.

export function SettingsSection({ className, children, stacked = false, ...props }: ComponentProps<"section"> & { stacked?: boolean }) {
  return (
    <section className={cn("@container scroll-mt-6 border-t pt-8 first:border-t-0 first:pt-0", className)} {...props}>
      {/* `stacked`: the title above, for content that needs the whole width (a list of people). */}
      <div className={cn("grid gap-4", !stacked && "@3xl:grid-cols-[15rem_minmax(0,1fr)] @3xl:gap-10")}>{children}</div>
    </section>
  );
}

export function SettingsHeader({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("grid content-start gap-1.5", className)} {...props} />;
}

export function SettingsTitle({ className, ...props }: ComponentProps<"h2">) {
  return <h2 className={cn("font-semibold", className)} {...props} />;
}

export function SettingsDescription({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("text-muted-foreground text-sm", className)} {...props} />;
}

export function SettingsContent({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("bg-card min-w-0 rounded-xl border p-5 shadow-xs", className)} {...props} />;
}
