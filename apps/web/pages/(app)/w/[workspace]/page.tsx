import { Button } from "@dotrix/ui/components/button";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { BotIcon, PlusIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useMemo, type ReactNode } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import { PageHeader } from "@/components/app-shell";
import { timeAgo } from "@/components/issues/issue-activity";
import { today, WorkspaceIssueRow } from "@/components/issues/workspace-issue-row";
import { ProjectTile } from "@/components/project-tile";
import { NotFound } from "@/components/states";
import { useWorkspaceActivity } from "@/lib/activity";
import { runTitle, useWorkspaceApprovals } from "@/lib/agent";
import { useMembers, useWorkspaceIssues } from "@/lib/issues";
import { can, canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace, useMe, useProjects } from "@/lib/queries";

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

function daysAgo(days: number): Date {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date;
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="bg-card rounded-xl border">
      <header className="flex h-12 items-center gap-2 border-b px-4">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="flex-1" />
        {action}
      </header>
      {children}
    </section>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: number | string; hint: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className={`text-2xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</span>
      <span className="text-muted-foreground text-xs">{hint}</span>
    </div>
  );
}

/** Your start page in a workspace: what waits for you, your issues, and how the projects are doing. */
export default function HomePage() {
  const { workspace, notFound } = useCurrentWorkspace();
  const me = useMe();
  const projects = useProjects(workspace?.id);
  const canSee = Boolean(workspace && workspace.role !== "guest");
  const approvals = useWorkspaceApprovals(workspace?.id, canSee);
  const mine = useWorkspaceIssues(canSee ? workspace?.id : undefined, { assignee: "me" });
  const all = useWorkspaceIssues(canSee ? workspace?.id : undefined, {});
  const canChat = can(workspace, "agents:chat");
  const agentActivity = useWorkspaceActivity(canChat ? workspace?.id : undefined, 6, { agents: true });
  const members = useMembers(canChat ? workspace?.id : undefined);
  const memberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);

  const stats = useMemo(() => {
    const issues = mine.data ?? [];
    const open = issues.filter((i) => i.status !== "done");
    const weekAgo = daysAgo(7);
    return {
      open: open.length,
      dueThisWeek: open.filter((i) => i.due && i.due >= today() && i.due <= today(7)).length,
      overdue: open.filter((i) => i.due && i.due < today()).length,
      doneThisWeek: issues.filter((i) => i.status === "done" && new Date(i.updated_at) >= weekAgo).length,
      next: open.slice(0, 6),
    };
  }, [mine.data]);

  const progress = useMemo(() => {
    const byProject = new Map<string, { done: number; total: number }>();
    for (const issue of all.data ?? []) {
      if (issue.type === "epic") continue;
      const counts = byProject.get(issue.project_id) ?? { done: 0, total: 0 };
      counts.total += 1;
      if (issue.status === "done") counts.done += 1;
      byProject.set(issue.project_id, counts);
    }
    return byProject;
  }, [all.data]);

  if (notFound) return <NotFound what="workspace" />;
  const base = workspace ? `/w/${workspace.slug}` : "";
  const waiting = approvals.data ?? [];
  const runs = [...new Map(waiting.map((a) => [a.run_id, a])).values()];
  const recentAgentWork = agentActivity.data?.pages[0] ?? [];
  const firstName = me.data?.display_name.split(" ")[0];

  return (
    <>
      <PageHeader
        title="Home"
        parent={workspace?.name}
        actions={
          canManageProjects(workspace?.role) && (
            <Button size="sm" variant="outline" asChild>
              <Link href={`${base}/projects/new`}>
                <PlusIcon />
                New project
              </Link>
            </Button>
          )
        }
      />
      <div className="flex w-full max-w-6xl flex-col gap-6 p-4 md:p-6">
        <div className="flex flex-col gap-1">
          <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            {new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <h2 className="text-2xl font-semibold tracking-tight">
            {greeting()}
            {firstName ? `, ${firstName}` : ""}
          </h2>
          <p className="text-muted-foreground text-sm">
            {!canSee
              ? "Guests see only what's shared with them."
              : runs.length || stats.overdue
                ? [
                    runs.length ? `${runs.length} ${runs.length === 1 ? "request is" : "requests are"} waiting for a decision` : null,
                    stats.overdue ? `${stats.overdue} of your issues ${stats.overdue === 1 ? "is" : "are"} overdue` : null,
                  ]
                    .filter(Boolean)
                    .join(", and ") + "."
                : "Nothing is waiting for you."}
          </p>
        </div>

        {canSee && (
          <div className="bg-card grid grid-cols-2 divide-x rounded-xl border md:grid-cols-4 [&>*:nth-child(3)]:border-l-0 md:[&>*:nth-child(3)]:border-l">
            <Stat label="Waiting for a decision" value={runs.length} hint="agent requests" tone={runs.length ? "text-primary" : ""} />
            <Stat label="My open issues" value={stats.open} hint={`${stats.dueThisWeek} due this week`} />
            <Stat label="Done this week" value={stats.doneThisWeek} hint="assigned to you" />
            <Stat label="Overdue" value={stats.overdue} hint="assigned to you" tone={stats.overdue ? "text-red-600 dark:text-red-400" : ""} />
          </div>
        )}

        {canSee && (
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <div className="flex flex-col gap-6">
              <Section
                title="Waiting for a decision"
                action={
                  <Link href={`${base}/approvals`} className="text-primary text-xs font-medium hover:underline">
                    Open notifications
                  </Link>
                }
              >
                {approvals.isLoading && <Skeleton className="m-4 h-10" />}
                {approvals.data && runs.length === 0 && <p className="text-muted-foreground px-4 py-6 text-sm">No agent is waiting on anyone.</p>}
                {runs.slice(0, 5).map((approval) => (
                  <Link
                    key={approval.run_id}
                    href={`${base}/approvals`}
                    className="hover:bg-muted/60 flex items-center gap-3 border-b px-4 py-3 text-sm last:border-b-0"
                  >
                    <span className="bg-brand-muted text-brand-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-lg">
                      <BotIcon className="size-4" />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{runTitle({ kind: "chat", message: approval.run_message })}</span>
                      <span className="text-muted-foreground truncate text-xs">
                        {approval.project_name} · {waiting.filter((a) => a.run_id === approval.run_id).length} to decide · {timeAgo(approval.created_at)}
                      </span>
                    </span>
                  </Link>
                ))}
              </Section>

              <Section
                title="My issues"
                action={
                  <Link href={`${base}/my-issues`} className="text-primary text-xs font-medium hover:underline">
                    All my issues
                  </Link>
                }
              >
                {mine.isLoading && <Skeleton className="m-4 h-24" />}
                {mine.data && stats.next.length === 0 && <p className="text-muted-foreground px-4 py-6 text-sm">Nothing assigned to you.</p>}
                {workspace && stats.next.map((issue) => <WorkspaceIssueRow key={issue.key} issue={issue} workspaceSlug={workspace.slug} />)}
              </Section>
            </div>

            <div className="flex flex-col gap-6">
              <Section
                title="Projects"
                action={
                  <Link href={`${base}/projects`} className="text-primary text-xs font-medium hover:underline">
                    All projects
                  </Link>
                }
              >
                {projects.isLoading && <Skeleton className="m-4 h-24" />}
                {projects.data?.length === 0 && <p className="text-muted-foreground px-4 py-6 text-sm">No projects yet.</p>}
                {projects.data?.map((project) => {
                  const counts = progress.get(project.id) ?? { done: 0, total: 0 };
                  const percent = counts.total ? Math.round((counts.done / counts.total) * 100) : 0;
                  return (
                    <Link
                      key={project.id}
                      href={`${base}/p/${project.key}`}
                      className="hover:bg-muted/60 flex flex-col gap-2 border-b px-4 py-3 text-sm last:border-b-0"
                    >
                      <span className="flex items-center gap-2">
                        <ProjectTile projectKey={project.key} className="size-4 text-[8px]" />
                        <span className="min-w-0 flex-1 truncate font-medium">{project.name}</span>
                        <span className="text-muted-foreground font-mono text-xs">
                          {counts.done}/{counts.total}
                        </span>
                      </span>
                      <span className="bg-muted h-1.5 overflow-hidden rounded-full" aria-label={`${percent}% done`}>
                        <span className="bg-primary block h-full rounded-full" style={{ width: `${percent}%` }} />
                      </span>
                    </Link>
                  );
                })}
              </Section>

              {canChat && (
                <Section
                  title="Agent activity"
                  action={
                    <Link href={`${base}/activity?show=agents`} className="text-primary text-xs font-medium hover:underline">
                      All activity
                    </Link>
                  }
                >
                  {agentActivity.isLoading && <Skeleton className="m-4 h-24" />}
                  {agentActivity.data && recentAgentWork.length === 0 && (
                    <p className="text-muted-foreground px-4 py-6 text-sm">The agents haven't done anything yet.</p>
                  )}
                  {workspace && recentAgentWork.length > 0 && (
                    <div className="px-4">
                      <ActivityFeed items={recentAgentWork} members={memberMap} workspaceSlug={workspace.slug} compact showProject />
                    </div>
                  )}
                </Section>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
