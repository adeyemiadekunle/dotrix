import { cn } from "@dotrix/ui/lib/utils";

import { Logo as Wordmark, Mark } from "@/src/core/icons";

/** dotrix's logo: the dot matrix with the wordmark, or the app icon alone. */
export function Logo({ className, withName = true }: { className?: string; withName?: boolean }) {
  return <span className={cn("flex items-center", className)}>{withName ? <Wordmark h={22} /> : <Mark px={26} />}</span>;
}
