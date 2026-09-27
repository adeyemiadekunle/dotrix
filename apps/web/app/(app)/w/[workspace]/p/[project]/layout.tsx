"use client";

import { Button } from "@pmagent/ui/components/button";
import { cn } from "@pmagent/ui/lib/utils";
import { MessageSquareIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";

import { ChatProvider, useChat } from "@/components/agent/chat-context";
import { ChatPanel } from "@/components/agent/chat-panel";
import { PageHeader } from "@/components/app-shell";
import { IssueDrawer } from "@/components/issues/issue-drawer";
import { NewIssueDialog } from "@/components/issues/new-issue-dialog";
import { NotFound } from "@/components/states";
import { useProjectScope } from "@/lib/queries";

const TABS = [
  { href: "board", label: "Board" },
  { href: "backlog", label: "Backlog" },
  { href: "chat", label: "Chat" },
  { href: "docs", label: "Docs" },
  { href: "overview", label: "Overview" },
];

function ProjectFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { workspace, project, canEdit } = useProjectScope();
  const chat = useChat();
  const [creating, setCreating] = useState(false);
  const onChatPage = pathname.endsWith("/chat");

  const base = workspace && project ? `/w/${workspace.slug}/p/${project.key}` : "";
  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          parent={workspace?.name}
          title={project?.name ?? "…"}
          actions={
            project && (
              <div className="flex gap-2">
                {!onChatPage && (
                  <Button
                    size="sm"
                    variant={chat.open ? "secondary" : "outline"}
                    onClick={() => chat.setOpen(!chat.open)}
                    aria-pressed={chat.open}
                  >
                    <MessageSquareIcon />
                    <span className="hidden sm:inline">Ask PM</span>
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
        <nav className="flex gap-4 overflow-x-auto border-b px-4 text-sm md:px-6" aria-label="Project">
          {TABS.map((tab) => {
            const active = pathname.endsWith(`/${tab.href}`);
            return (
              <Link
                key={tab.href}
                href={`${base}/${tab.href}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "-mb-px shrink-0 border-b-2 border-transparent py-2.5 transition-colors",
                  active ? "border-foreground font-medium" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
              </Link>
            );
          })}
        </nav>
        {children}
      </div>
      {!onChatPage && <ChatPanel />}
      <Suspense>
        <IssueDrawer />
        {creating && <NewIssueDialog open={creating} onOpenChange={setCreating} />}
      </Suspense>
    </div>
  );
}

export default function ProjectLayout({ children }: { children: ReactNode }) {
  const { project, notFound } = useProjectScope();
  if (notFound) return <NotFound what="project" />;
  return (
    <ChatProvider projectId={project?.id}>
      <ProjectFrame>{children}</ProjectFrame>
    </ChatProvider>
  );
}
