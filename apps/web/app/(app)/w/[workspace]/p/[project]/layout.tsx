"use client";

import { Button } from "@pmagent/ui/components/button";
import { cn } from "@pmagent/ui/lib/utils";
import { InboxIcon, MessageSquareIcon, PlusIcon, SettingsIcon, StarIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";

import { AfterHydration } from "@/components/after-hydration";
import { ChatProvider, useChat } from "@/components/agent/chat-context";
import { TriageDialog } from "@/components/agent/triage-dialog";
import { PageHeader } from "@/components/app-shell";
import { ProjectTile } from "@/components/project-tile";
import { IssueDrawer } from "@/components/issues/issue-drawer";
import { NewIssueDialog } from "@/components/issues/new-issue-dialog";
import { NotFound } from "@/components/states";
import { useProjectScope } from "@/lib/queries";
import { useStarredProjects, useToggleStar } from "@/lib/stars";

// Every project has the same views. Chat is the workspace's (about this project via "Ask in
// Chat"); a summary is something you ask it for.
const TABS = [
  { href: "overview", label: "Overview" },
  { href: "board", label: "Board" },
  { href: "list", label: "List" },
  { href: "table", label: "Table" },
  { href: "timeline", label: "Timeline" },
  { href: "files", label: "Files" },
  { href: "knowledge", label: "Knowledge" },
  { href: "activity", label: "Activity" },
];

function ProjectFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { workspace, project, scope, canEdit } = useProjectScope();
  const chat = useChat();
  const [creating, setCreating] = useState(false);
  const [triaging, setTriaging] = useState(false);
  const starred = useStarredProjects(workspace?.id);
  const toggleStar = useToggleStar(workspace?.id);
  const isStarred = Boolean(project && starred.data?.includes(project.id));

  const base = workspace && project ? `/w/${workspace.slug}/p/${project.key}` : "";
  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <PageHeader
          parent={workspace?.name}
          icon={project && <ProjectTile projectKey={project.key} />}
          title={project?.name ?? "…"}
          actions={
            project && (
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => toggleStar.mutate({ projectId: project.id, starred: !isStarred })}
                  aria-pressed={isStarred}
                  aria-label={isStarred ? "Unstar project" : "Star project"}
                  title={isStarred ? "Unstar" : "Star: show it first in the sidebar and on Projects"}
                >
                  <StarIcon className={cn(isStarred && "fill-warning text-warning")} />
                </Button>
                <Button size="sm" variant="outline" asChild>
                  <Link href={chat.href} aria-label="Ask in Chat" title="Ask the agents about this project">
                    <MessageSquareIcon />
                    <span className="hidden sm:inline">Ask in Chat</span>
                  </Link>
                </Button>
                {canEdit && (
                  <Button size="sm" variant="outline" onClick={() => setTriaging(true)} title="Triage a bug report or request">
                    <InboxIcon />
                    <span className="hidden sm:inline">Triage</span>
                  </Button>
                )}
                {canEdit && (
                  <Button size="sm" onClick={() => setCreating(true)}>
                    <PlusIcon />
                    <span className="hidden sm:inline">New issue</span>
                  </Button>
                )}
              </div>
            )
          }
        />
        <div className="relative shrink-0 border-b">
          <nav
            className="flex items-center gap-1 overflow-x-auto px-2 text-sm [scrollbar-width:none] md:px-4"
            aria-label="Project"
          >
            {TABS.map((tab) => {
              const active = pathname.endsWith(`/${tab.href}`);
              return (
                <Link
                  key={tab.href}
                  href={`${base}/${tab.href}`}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "-mb-px shrink-0 border-b-2 border-transparent px-2 py-2.5 transition-colors",
                    active ? "border-primary text-foreground font-medium" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {tab.label}
                </Link>
              );
            })}
            <span className="flex-1" />
            <Link
              href={`${base}/settings`}
              aria-current={pathname.endsWith("/settings") ? "page" : undefined}
              aria-label="Project settings"
              title="Project settings"
              className={cn(
                "-mb-px flex shrink-0 items-center gap-1.5 border-b-2 border-transparent px-2 py-2.5 transition-colors",
                pathname.endsWith("/settings")
                  ? "border-primary text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <SettingsIcon className="size-4" />
              <span className="hidden lg:inline">Settings</span>
            </Link>
          </nav>
          {/* On narrow screens the tabs scroll sideways; the fade says there's more. */}
          <div className="from-background pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l md:hidden" />
        </div>
        {/* The tab's content, the chat panel, and the issue drawer come from browser-side
            queries: rendered after hydration, so data that arrives first can't make them
            differ from the server's markup (see AfterHydration). */}
        <AfterHydration>{children}</AfterHydration>
      </div>
      <AfterHydration>
        <Suspense>
          <IssueDrawer />
          {creating && <NewIssueDialog open={creating} onOpenChange={setCreating} />}
          {triaging && scope && <TriageDialog scope={scope} open={triaging} onOpenChange={setTriaging} />}
        </Suspense>
      </AfterHydration>
    </div>
  );
}

export default function ProjectLayout({ children }: { children: ReactNode }) {
  const { workspace, project, notFound } = useProjectScope();
  if (notFound) return <NotFound what="project" />;
  return (
    <ChatProvider workspaceSlug={workspace?.slug} projectKey={project?.key}>
      <ProjectFrame>{children}</ProjectFrame>
    </ChatProvider>
  );
}
