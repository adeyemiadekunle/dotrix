import { Avatar, AvatarFallback, AvatarImage } from "@pmagent/ui/components/avatar";
import { cn } from "@pmagent/ui/lib/utils";

import { initials } from "@/lib/labels";

/** A person's photo, or their initials without one (or while it loads). */
export function UserAvatar({ name, src, className }: { name: string; src?: string; className?: string }) {
  return (
    <Avatar className={cn("size-8", className)}>
      {src && <AvatarImage src={src} alt="" className="object-cover" />}
      <AvatarFallback className="text-xs">{initials(name)}</AvatarFallback>
    </Avatar>
  );
}
