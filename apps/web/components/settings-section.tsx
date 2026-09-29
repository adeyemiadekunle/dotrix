import { cn } from "@pmagent/ui/lib/utils";
import type { ComponentProps } from "react";

// A settings page is a column of sections: what the section is on the left, its controls on the
// right (stacked on narrow screens). The parts mirror Card's, so a card converts by renaming.

export function SettingsSection({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn(
        "grid scroll-mt-6 gap-4 border-t pt-8 first:border-t-0 first:pt-0 md:grid-cols-[15rem_minmax(0,1fr)] md:gap-10",
        className,
      )}
      {...props}
    />
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
