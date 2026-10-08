import { Button } from "@pmagent/ui/components/button";
import { SearchXIcon, type LucideIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import type { ReactNode } from "react";

import { PageHeader } from "@/components/app-shell";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    // Sized to its content and placed where the page's content starts, so the action is where
    // the eye lands (not floating in the middle of a full-height box).
    <div className="bg-card flex w-full flex-col items-center gap-3 self-start rounded-xl border px-6 py-10 text-center">
      <div className="bg-brand-muted text-brand-muted-foreground flex size-10 items-center justify-center rounded-lg">
        <Icon className="size-5" />
      </div>
      <div className="grid gap-1">
        <h2 className="font-semibold">{title}</h2>
        <p className="text-muted-foreground max-w-md text-sm text-balance">{description}</p>
      </div>
      {action}
    </div>
  );
}

/** Also shown for things you can't see: the API answers 404 rather than revealing they exist. */
export function NotFound({ what }: { what: string }) {
  return (
    <>
      <PageHeader title="Not found" />
      <div className="flex flex-1 items-center justify-center p-6 [&>div]:max-w-lg [&>div]:self-center">
        <EmptyState
          icon={SearchXIcon}
          title={`This ${what} doesn't exist`}
          description={`Or you don't have access to it. Check the link, or ask someone in the ${what} to add you.`}
          action={
            <Button asChild variant="outline">
              <Link href="/">Go home</Link>
            </Button>
          }
        />
      </div>
    </>
  );
}
