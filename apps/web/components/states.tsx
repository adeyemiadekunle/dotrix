import { Button } from "@pmagent/ui/components/button";
import { SearchXIcon, type LucideIcon } from "lucide-react";
import Link from "next/link";
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
    <div className="flex flex-1 flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-10 text-center">
      <div className="bg-muted flex size-10 items-center justify-center rounded-full">
        <Icon className="text-muted-foreground size-5" />
      </div>
      <div className="grid gap-1">
        <h2 className="font-medium">{title}</h2>
        <p className="text-muted-foreground max-w-sm text-sm">{description}</p>
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
      <div className="flex flex-1 items-center justify-center p-6">
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
