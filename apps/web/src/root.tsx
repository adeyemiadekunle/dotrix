import { Button } from "@pmagent/ui/components/button";
import { Outlet, useMatches } from "@tanstack/react-router";
import { SearchXIcon } from "lucide-react";
import { useEffect } from "react";

import { EmptyState } from "@/components/states";
import { Link } from "@/lib/navigation";

const APP_NAME = "pmagent";

/** Every page: names the browser tab after the deepest route that has a title. */
export function RootLayout() {
  const title = useMatches({
    select: (matches) => matches.findLast((match) => match.staticData.title)?.staticData.title,
  });
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME;
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
