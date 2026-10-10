import { Button } from "@dotrix/ui/components/button";
import { Outlet, useMatches } from "@tanstack/react-router";
import { SearchXIcon } from "lucide-react";
import { useEffect } from "react";

import { EmptyState } from "@/components/states";
import { Link } from "@/lib/navigation";

const APP_NAME = "dotrix";

/** Every page: names the browser tab after the deepest route that has a title (and its project). */
export function RootLayout() {
  const title = useMatches({
    select: (matches) => {
      const match = matches.findLast((m) => m.staticData.title);
      if (!match) return undefined;
      const project = (match.params as { project?: string }).project;
      return project ? `${match.staticData.title} · ${project.toUpperCase()}` : match.staticData.title;
    },
  });
  // Routes without a title (the workspace) set their own.
  useEffect(() => {
    if (title) document.title = `${title} · ${APP_NAME}`;
  }, [title]);
  return <Outlet />;
}

/** An address that's no page of the app. */
export function NotFoundPage() {
  return (
    <div className="flex min-h-svh items-center justify-center p-6 [&>div]:max-w-lg [&>div]:self-center">
      <EmptyState
        icon={SearchXIcon}
        title="This page doesn't exist"
        description="Check the link, or go back to your workspace."
        action={
          <Button asChild variant="outline">
            <Link href="/">Go home</Link>
          </Button>
        }
      />
    </div>
  );
}
