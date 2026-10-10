import { Skeleton } from "@dotrix/ui/components/skeleton";
import { Link } from "@/lib/navigation";
import { useMemo, type ReactNode } from "react";

import { PageHeader } from "@/components/app-shell";
import { STATUSES, STATUS_META } from "@/components/issues/meta";
import { today } from "@/components/issues/workspace-issue-row";
import { ProjectTile } from "@/components/project-tile";
import { NotFound } from "@/components/states";
import { agentLabel, useWorkspaceAgentUsage, useWorkspaceApprovals } from "@/lib/agent";
import { useMembers, useWorkspaceIssues } from "@/lib/issues";
import { can } from "@/lib/labels";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

// Status colours for the bars, matching the status icons.
const BAR: Record<string, string> = {
  todo: "bg-slate-400 dark:bg-slate-500",
  in_progress: "bg-blue-600 dark:bg-blue-400",
  blocked: "bg-red-600 dark:bg-red-400",
  review: "bg-violet-600 dark:bg-violet-400",
  done: "bg-emerald-600 dark:bg-emerald-400",
};

function Card({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="bg-card rounded-xl border">
      <header className="flex h-12 items-center gap-2 border-b px-4">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="flex-1" />
        {aside}
      </header>
      {children}
    </section>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className={`text-2xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</span>
      <span className="text-muted-foreground text-xs">{hint}</span>
    </div>
  );
}

const compact = new Intl.NumberFormat(undefined, { notation: "compact" });

/** How every project in the workspace is doing: portfolio, issues by status, workload, agents. */
export default function WorkspaceOverviewPage() {
  const { workspace, notFound } = useCurrentWorkspace();
  const canSee = Boolean(workspace && workspace.role !== "guest");
  const projects = useProjects(workspace?.id);
  const issues = useWorkspaceIssues(canSee ? workspace?.id : undefined, {});
  const members = useMembers(workspace?.id);
  const approvals = useWorkspaceApprovals(workspace?.id, canSee);
  const showUsage = can(workspace, "usage:view");
  const usage = useWorkspaceAgentUsage(workspace?.id, showUsage);

  const data = useMemo(() => {
    const all = (issues.data ?? []).filter((i) => i.type !== "epic");
    const open = all.filter((i) => i.status !== "done");
    const weekAgo = new Date(Date.now() - 7 * 24 * 3600 * 1000);
    const perProject = new Map<string, { total: number; done: number; open: number; overdue: number }>();
    for (const issue of all) {
      const p = perProject.get(issue.project_id) ?? { total: 0, done: 0, open: 0, overdue: 0 };
      p.total += 1;
      if (issue.status === "done") p.done += 1;
      else {
        p.open += 1;
        if (issue.due && issue.due < today()) p.overdue += 1;
      }
      perProject.set(issue.project_id, p);
    }
    const workload = new Map<string, number>();
    for (const issue of open) {
      if (issue.assignee_user_id) workload.set(issue.assignee_user_id, (workload.get(issue.assignee_user_id) ?? 0) + 1);
    }
    return {
      total: all.length,
      open: open.length,
      overdue: open.filter((i) => i.due && i.due < today()).length,
      doneThisWeek: all.filter((i) => i.status === "done" && new Date(i.updated_at) >= weekAgo).length,
      byStatus: Object.fromEntries(STATUSES.map((s) => [s, all.filter((i) => i.status === s).length])),
      perProject,
      workload: [...workload.entries()].sort((a, b) => b[1] - a[1]),
    };
  }, [issues.data]);

  if (notFound) return <NotFound what="workspace" />;
  const base = workspace ? `/w/${workspace.slug}` : "";
  const waitingRuns = new Set((approvals.data ?? []).map((a) => a.run_id)).size;
  const names = new Map(members.data?.map((m) => [m.user_id, m.display_name]));
  const maxLoad = data.workload[0]?.[1] ?? 1;

  return (
    <>
      <PageHeader title="Overview" parent={workspace?.name} />
      <div className="flex w-full max-w-6xl flex-col gap-6 p-4 md:p-6">
        <p className="text-muted-foreground text-sm">How every project in {workspace?.name ?? "the workspace"} is doing.</p>

        <div className="bg-card grid grid-cols-2 divide-x rounded-xl border md:grid-cols-4 [&>*:nth-child(3)]:border-l-0 md:[&>*:nth-child(3)]:border-l">
          <Stat label="Projects" value={projects.data?.length ?? "–"} hint="you can see" />
          <Stat label="Open issues" value={data.open} hint={`${data.overdue} overdue`} tone={data.overdue ? "" : ""} />
          <Stat label="Done this week" value={data.doneThisWeek} hint="across every project" />
          <Stat
            label="Waiting for a decision"
            value={waitingRuns}
            hint="agent requests"
            tone={waitingRuns ? "text-primary" : ""}
          />
        </div>

        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
          <Card title="Portfolio" aside={<Link href={`${base}/projects`} className="text-primary text-xs font-medium hover:underline">All projects</Link>}>
            {(projects.isLoading || issues.isLoading) && <Skeleton className="m-4 h-32" />}
            {projects.data && issues.data && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-muted-foreground text-left text-xs">
                      <th className="px-4 py-2 font-medium">Project</th>
                      <th className="px-4 py-2 font-medium">Progress</th>
                      <th className="px-4 py-2 text-right font-medium">Open</th>
                      <th className="px-4 py-2 text-right font-medium">Overdue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {projects.data.map((project) => {
                      const p = data.perProject.get(project.id) ?? { total: 0, done: 0, open: 0, overdue: 0 };
                      const percent = p.total ? Math.round((p.done / p.total) * 100) : 0;
                      return (
                        <tr key={project.id} className="border-t">
                          <td className="px-4 py-2.5">
                            <Link href={`${base}/p/${project.key}`} className="flex items-center gap-2 font-medium hover:underline">
                              <ProjectTile projectKey={project.key} className="size-4 text-[8px]" />
                              {project.name}
                            </Link>
                          </td>
                          <td className="px-4 py-2.5">
                            <span className="flex items-center gap-2">
                              <span className="bg-muted h-1.5 w-28 overflow-hidden rounded-full">
                                <span className="bg-primary block h-full" style={{ width: `${percent}%` }} />
                              </span>
                              <span className="text-muted-foreground font-mono text-xs">{percent}%</span>
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-right tabular-nums">{p.open}</td>
                          <td className={`px-4 py-2.5 text-right tabular-nums ${p.overdue ? "font-medium text-red-600 dark:text-red-400" : ""}`}>
                            {p.overdue}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Issues by status">
            <div className="flex flex-col gap-3 px-4 py-4">
              <div className="bg-muted flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden>
                {STATUSES.map((s) =>
                  data.byStatus[s] ? <span key={s} className={BAR[s]} style={{ width: `${(data.byStatus[s] / data.total) * 100}%` }} /> : null,
                )}
              </div>
              <ul className="flex flex-col gap-1.5 text-sm">
                {STATUSES.map((s) => (
                  <li key={s} className="flex items-center gap-2">
                    <span className={`size-2 rounded-sm ${BAR[s]}`} />
                    {STATUS_META[s].label}
                    <span className="text-muted-foreground ml-auto font-mono text-xs">{data.byStatus[s] ?? 0}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Card>
        </div>

        <div className="grid items-start gap-6 lg:grid-cols-2">
          <Card title="Workload" aside={<span className="text-muted-foreground text-xs">open issues per person</span>}>
            <div className="flex flex-col gap-2.5 px-4 py-4 text-sm">
              {issues.data && data.workload.length === 0 && <p className="text-muted-foreground">Nobody has open issues assigned.</p>}
              {data.workload.map(([userId, count]) => (
                <Link key={userId} href={`${base}/tasks?assignee=${userId}`} className="grid grid-cols-[8rem_minmax(0,1fr)_2rem] items-center gap-3 hover:underline">
                  <span className="truncate">{names.get(userId) ?? "Former member"}</span>
                  <span className="bg-muted h-1.5 overflow-hidden rounded-full">
                    <span className="bg-primary block h-full" style={{ width: `${(count / maxLoad) * 100}%` }} />
                  </span>
                  <span className="text-muted-foreground text-right font-mono text-xs">{count}</span>
                </Link>
              ))}
            </div>
          </Card>

          {showUsage && (
            <Card title="Agents this week" aside={<span className="text-muted-foreground text-xs">owners and admins</span>}>
              {usage.isLoading && <Skeleton className="m-4 h-20" />}
              {usage.data && (
                <div className="flex flex-col gap-3 px-4 py-4 text-sm">
                  <div className="grid grid-cols-3 gap-3">
                    <Stat label="Runs" value={usage.data.runs} hint={`${usage.data.model_calls} model calls`} />
                    <Stat label="Tokens" value={compact.format(usage.data.input_tokens + usage.data.output_tokens)} hint="in and out" />
                    <Stat
                      label="Changes approved"
                      value={`${usage.data.approved} of ${usage.data.approved + usage.data.rejected}`}
                      hint={`${usage.data.rejected} rejected`}
                    />
                  </div>
                  {usage.data.by_agent.length > 0 && (
                    <p className="text-muted-foreground text-xs">
                      Most used:{" "}
                      {usage.data.by_agent
                        .slice(0, 3)
                        .map((a) => `${a.agent === "auto" ? "Auto" : agentLabel(a.agent)} (${a.runs})`)
                        .join(", ")}
                    </p>
                  )}
                </div>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
