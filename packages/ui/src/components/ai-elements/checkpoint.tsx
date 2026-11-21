import type { ReactNode } from "react";
import { BookmarkIcon } from "lucide-react";

import { Button } from "@dotrix/ui/components/button";
import { Marker, MarkerContent, MarkerIcon } from "@dotrix/ui/components/marker";
import { cn } from "@dotrix/ui/lib/utils";

/**
 * A point in the conversation you can return to (shadcn/ui AI Elements Checkpoint, built on
 * Marker). `onRestore` adds a Restore button; leave it out for a plain marker.
 */
function Checkpoint({
  label,
  onRestore,
  canRestore = true,
  className,
}: {
  label: ReactNode;
  onRestore?: () => void;
  canRestore?: boolean;
  className?: string;
}) {
  return (
    <Marker variant="separator" className={cn("my-2", className)}>
      <MarkerIcon>
        <BookmarkIcon />
      </MarkerIcon>
      <MarkerContent className="inline-flex items-center gap-2">
        {label}
        {onRestore && canRestore && (
          <Button size="xs" variant="outline" onClick={onRestore}>
            Restore
          </Button>
        )}
      </MarkerContent>
    </Marker>
  );
}

export { Checkpoint };
