"use client";

import { Button } from "@pmagent/ui/components/button";
import { cn } from "@pmagent/ui/lib/utils";
import { ChevronDownIcon, ChevronRightIcon, MessageSquarePlusIcon, PlusIcon, ShieldAlertIcon } from "lucide-react";
import { Suspense, useMemo, useState } from "react";

import { Conversation } from "@/components/agent/conversation";
import { ThreadTitle } from "@/components/agent/thread-title";
import { AfterHydration } from "@/components/after-hydration";
import { PageHeader } from "@/components/app-shell";
import { timeAgo } from "@/components/issues/issue-activity";
import { ProjectTile } from "@/components/project-tile";
import { NotFound } from "@/components/states";
import { useWorkspaceThreads } from "@/lib/agent";
import { useMembers } from "@/lib/issues";
import { can } from "@/lib/labels";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";
import { useSearchParam, useSetSearchParams } from "@/lib/url-state";

/**
 * One Chat for the workspace. Conversations are listed by project; a conversation is about one
 * project for now (`?project=KEY&thread=ID`), so the agents read that project.
 */
function WorkspaceChat() {
  const { workspace, notFound } = useCurrentWorkspace();
  const projects = useProjects(workspace?.id);
  const canChat = can(workspace, "agents:chat");
  const threads = useWorkspaceThreads(workspace?.id, canChat);
  const members = useMembers(workspace?.id);
  const names = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m.display_name])), [members.data]);
  const [projectKey] = useSearchParam("project");
  const [threadId] = useSearchParam("thread");
  const setParams = useSetSearchParams();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const list = projects.data ?? [];
  // With only one project there's nothing to choose.
  const project = list.find((p) => p.key === projectKey?.toUpperCase()) ?? (list.length === 1 ? list[0] : undefined);
  const scope = workspace && project ? { workspaceId: workspace.id, projectId: project.id } : undefined;
  const byProject = useMemo(() => {
    const groups = new Map<string, NonNullable<typeof threads.data>>();
    for (const thread of threads.data ?? []) {
      groups.set(thread.project_id, [...(groups.get(thread.project_id) ?? []), thread]);
    }
    return groups;
  }, [threads.data]);

  if (notFound) return <NotFound what="workspace" />;
  const open = (key: string | null, thread: string | null) => setParams({ project: key, thread });

  return (
    <>
      <PageHeader title="Chat" parent={workspace?.name} />
      {/* Fills the window below the header (see AppShell), so only the messages scroll. */}
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-72 shrink-0 flex-col border-r md:flex">
          <div className="p-3">
            <Button variant="outline" size="sm" className="w-full justify-start" onClick={() => open(project?.key ?? null, null)}>
              <MessageSquarePlusIcon />
              New chat
            </Button>
          </div>
          <nav className="flex-1 overflow-y-auto px-2 pb-3" aria-label="Conversations">
            {list.map((p) => {
              const conversations = byProject.get(p.id) ?? [];
              const isCollapsed = collapsed[p.id] ?? false;
              return (
                <div key={p.id} className="grid gap-0.5 pb-2">
                  <div className="flex items-center gap-1 pr-1">
                    <button
                      type="button"
                      onClick={() => setCollapsed((c) => ({ ...c, [p.id]: !isCollapsed }))}
                      aria-expanded={!isCollapsed}
                      className="hover:bg-muted flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1.5 py-1.5 text-left text-sm font-medium"
                    >
                      {isCollapsed ? <ChevronRightIcon className="size-3.5 shrink-0" /> : <ChevronDownIcon className="size-3.5 shrink-0" />}
                      <ProjectTile projectKey={p.key} className="size-4 text-[8px]" />
                      <span className="truncate">{p.name}</span>
                      {isCollapsed && conversations.length > 0 && (
                        <span className="text-muted-foreground text-xs font-normal">{conversations.length}</span>
                      )}
                    </button>
                    {canChat && (
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        aria-label={`New chat in ${p.name}`}
                        title={`New chat in ${p.name}`}
                        onClick={() => open(p.key, null)}
                      >
                        <PlusIcon />
                      </Button>
                    )}
                  </div>
                  {!isCollapsed &&
                    conversations.map((t) => (
                      <button
                        key={t.thread_id}
                        type="button"
                        onClick={() => open(p.key, t.thread_id)}
                        aria-current={t.thread_id === threadId ? "true" : undefined}
                        className={cn(
                          "hover:bg-muted grid w-full gap-0.5 rounded-md py-1.5 pr-2 pl-7 text-left text-sm",
                          t.thread_id === threadId && "bg-muted",
                        )}
                      >
                        <span className="flex items-center gap-1.5">
                          {t.waiting && <ShieldAlertIcon className="text-warning size-3.5 shrink-0" />}
                          <span className="truncate">{t.title}</span>
                        </span>
                        <span className="text-muted-foreground text-xs">{timeAgo(t.updated_at)}</span>
                      </button>
                    ))}
                  {!isCollapsed && conversations.length === 0 && (
                    <p className="text-muted-foreground py-1 pl-7 text-xs">No conversations yet.</p>
                  )}
                </div>
              );
            })}
            {projects.data?.length === 0 && (
              <p className="text-muted-foreground px-2 text-xs">Create a project first; the agents work from its documents and board.</p>
            )}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-11 shrink-0 items-center gap-2 border-b px-4">
            {scope ? (
              <ThreadTitle scope={scope} threadId={threadId} fallback="New chat" className="min-w-0 flex-1" />
            ) : (
              <span className="flex-1 text-sm font-medium">New chat</span>
            )}
            {/* Which project the conversation is about: fixed once it has started. */}
            <label className="text-muted-foreground flex items-center gap-1.5 text-xs">
              About
              <select
                aria-label="Project"
                value={project?.key ?? ""}
                disabled={Boolean(threadId)}
                onChange={(e) => open(e.target.value || null, null)}
                className="bg-background text-foreground h-7 rounded-md border px-1.5 text-xs disabled:opacity-100"
              >
                {!project && <option value="">Choose a project</option>}
                {list.map((p) => (
                  <option key={p.id} value={p.key}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            {/* Phones: the conversation list is a menu. */}
            <select
              aria-label="Conversation"
              value={threadId ?? ""}
              onChange={(e) => {
                const t = threads.data?.find((x) => x.thread_id === e.target.value);
                open(t?.project_key ?? project?.key ?? null, t?.thread_id ?? null);
              }}
              className="bg-background h-7 max-w-36 rounded-md border px-1.5 text-xs md:hidden"
            >
              <option value="">New chat</option>
              {threads.data?.map((t) => (
                <option key={t.thread_id} value={t.thread_id}>
                  {t.project_key} · {t.title}
                </option>
              ))}
            </select>
          </div>
          {scope ? (
            <Conversation
              key={`${scope.projectId}:${threadId ?? "new"}`}
              scope={scope}
              threadId={threadId}
              onThread={(id) => open(project!.key, id)}
              names={names}
              canChat={canChat}
              canDecide={can(workspace, "agents:approve")}
            />
          ) : (
            <div className="grid flex-1 content-center justify-items-center gap-4 p-6 text-center">
              <div className="grid gap-1">
                <p className="font-medium">Which project is it about?</p>
                <p className="text-muted-foreground text-sm">The agents read that project&apos;s documents and board.</p>
              </div>
              <div className="flex max-w-xl flex-wrap justify-center gap-2">
                {list.map((p) => (
                  <Button key={p.id} variant="outline" size="sm" onClick={() => open(p.key, null)}>
                    <ProjectTile projectKey={p.key} className="size-4 text-[8px]" />
                    {p.name}
                  </Button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default function ChatPage() {
  return (
    <Suspense>
      <AfterHydration>
        <WorkspaceChat />
      </AfterHydration>
    </Suspense>
  );
}
