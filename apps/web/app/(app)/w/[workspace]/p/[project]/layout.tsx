"use client";

import { Button } from "@pmagent/ui/components/button";
import { cn } from "@pmagent/ui/lib/utils";
import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";

import { PageHeader } from "@/components/app-shell";
import { IssueDrawer } from "@/components/issues/issue-drawer";
import { NewIssueDialog } from "@/components/issues/new-issue-dialog";
import { NotFound } from "@/components/states";
import { useProjectScope } from "@/lib/queries";

const TABS = [
  { href: "board", label: "Board" },
  { href: "backlog", label: "Backlog" },
  { href: "docs", label: "Docs" },
  { href: "overview", label: "Overview" },
];

export default function ProjectLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { workspace, project, notFound, canEdit } = useProjectScope();
  const [creating, setCreating] = useState(false);
  if (notFound) return <NotFound what="project" />;

  const base = workspace && project ? `/w/${workspace.slug}/p/${project.key}` : "";
  return (
    <>
      <PageHeader
        parent={workspace?.name}
        title={project?.name ?? "…"}
        actions={
          canEdit &&
          project && (
            <Button size="sm" onClick={() => setCreating(true)}>
              <PlusIcon />
              New issue
            </Button>
          )
        }
      />
      <nav className="flex gap-4 border-b px-4 text-sm md:px-6" aria-label="Project">
        {TABS.map((tab) => {
          const active = pathname.endsWith(`/${tab.href}`);
          return (
            <Link
              key={tab.href}
              href={`${base}/${tab.href}`}
              aria-current={active ? "page" : undefined}
              className={cn(
                "-mb-px border-b-2 border-transparent py-2.5 transition-colors",
                active ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
      {children}
      <Suspense>
        <IssueDrawer />
        {creating && <NewIssueDialog open={creating} onOpenChange={setCreating} />}
      </Suspense>
    </>
  );
}
