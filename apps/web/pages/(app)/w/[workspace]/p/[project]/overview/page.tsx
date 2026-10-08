import { Button } from "@pmagent/ui/components/button";
import { Progress } from "@pmagent/ui/components/progress";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { MessageSquareIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useMemo, type ReactNode } from "react";

import { useChat } from "@/components/agent/chat-context";
import { ActivityFeed } from "@/components/activity-feed";
import { STATUS_META, STATUSES, TypeIcon, type MemberMap } from "@/components/issues/meta";
import { formatDue, today } from "@/components/issues/workspace-issue-row";
import { useProjectActivity } from "@/lib/activity";
import { modelName } from "@/lib/agent";
import { useBoard, useEpics, useMembers, type IssueSummary } from "@/lib/issues";
import { PROJECT_SOURCE_LABELS } from "@/lib/labels";
import { useProjectScope } from "@/lib/queries";

// Status colours for the progress bar, matching the status icons.
const BAR: Record<string, string> = {
  todo: "bg-slate-400 dark:bg-slate-500",
  in_progress: "bg-blue-600 dark:bg-blue-400",
  blocked: "bg-red-600 dark:bg-red-400",
  review: "bg-violet-600 dark:bg-violet-400",
  done: "bg-emerald-600 dark:bg-emerald-400",
};

function Card({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
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

/** The project at a glance: what it's for, how far along, what's next, and what just happened. */
export default function OverviewPage() {
  const { workspace, project, scope } = useProjectScope();
  const chat = useChat();
  const board = useBoard(scope, {});
  const epics = useEpics(scope);
  const members = useMembers(workspace?.id);
  const activity = useProjectActivity(scope, 8);
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);
  const base = workspace && project ? `/w/${workspace.slug}/p/${project.key}` : "";

  const { counts, total, done, next } = useMemo(() => {
    const columns = board.data?.columns ?? [];
    const issues = columns.flatMap((c) => c.issues).filter((i) => i.type !== "epic");
    const counts = Object.fromEntries(STATUSES.map((s) => [s, issues.filter((i) => i.status === s).length]));
    const open = issues.filter((i) => i.status !== "done");
    // Coming up: dated work soonest first (overdue on top), then the rest in backlog order.
    const dated = open.filter((i) => i.due).sort((a, b) => a.due!.localeCompare(b.due!));
    const next: IssueSummary[] = [...dated, ...open.filter((i) => !i.due)].slice(0, 6);
    return { counts, total: issues.length, done: counts.done ?? 0, next };
  }, [board.data]);
  const percent = total ? Math.round((done / total) * 100) : 0;

  return (
    <div className="grid w-full max-w-6xl items-start gap-6 p-4 md:p-6 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col gap-6">
        <Card
          title="About"
          action={
            <Link href={`${base}/knowledge?file=project.md`} className="text-primary text-xs font-medium hover:underline">
              Open project.md
            </Link>
          }
        >
          <p className="text-muted-foreground px-4 py-3 text-sm leading-relaxed">
            {project?.description || "No description yet. Add one in the project's settings."}
          </p>
        </Card>

        <Card title="Progress" action={<span className="text-muted-foreground text-xs">{done} of {total} issues done</span>}>
          <div className="flex flex-col gap-3 px-4 py-4">
            {board.isLoading ? (
              <Skeleton className="h-16" />
            ) : (
              <>
                <span className="text-3xl font-semibold tabular-nums">{percent}%</span>
                <div className="bg-muted flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden>
                  {STATUSES.map((s) =>
                    counts[s] ? <span key={s} className={BAR[s]} style={{ width: `${(counts[s] / total) * 100}%` }} /> : null,
                  )}
                </div>
                <ul className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  {STATUSES.map((s) => (
                    <li key={s} className="flex items-center gap-1.5">
                      <span className={`size-2 rounded-sm ${BAR[s]}`} />
                      {STATUS_META[s].label} {counts[s] ?? 0}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </Card>

        <Card
          title="Coming up"
          action={
            <Link href={`${base}/list`} className="text-primary text-xs font-medium hover:underline">
              View list
            </Link>
          }
        >
          {board.data && next.length === 0 && <p className="text-muted-foreground px-4 py-6 text-sm">Nothing open.</p>}
          {next.map((issue) => {
            const overdue = issue.due !== null && issue.due < today();
            return (
              <Link
                key={issue.key}
                href={`${base}/board?issue=${issue.key}`}
                className="hover:bg-muted/60 flex items-center gap-3 border-b px-4 py-2.5 text-sm last:border-b-0"
              >
                <TypeIcon type={issue.type} />
                <span className="text-muted-foreground w-16 shrink-0 font-mono text-xs">{issue.key}</span>
                <span className="min-w-0 flex-1 truncate">{issue.title}</span>
                <span className="text-muted-foreground hidden w-24 text-xs sm:inline">{STATUS_META[issue.status].label}</span>
                <span className={`w-14 text-right text-xs ${overdue ? "font-medium text-red-600 dark:text-red-400" : "text-muted-foreground"}`}>
                  {issue.due ? formatDue(issue.due) : ""}
                </span>
              </Link>
            );
          })}
        </Card>

        <Card title="Epics">
          {epics.data?.length === 0 && (
            <p className="text-muted-foreground px-4 py-6 text-sm">No epics yet. An epic groups the stories of one feature.</p>
          )}
          {epics.data?.map((epic) => (
            <Link
              key={epic.key}
              href={`${base}/list?epic=${epic.key}`}
              className="hover:bg-muted/60 flex items-center gap-3 border-b px-4 py-2.5 text-sm last:border-b-0"
            >
              <span className="min-w-0 flex-1 truncate">{epic.title}</span>
              <Progress value={epic.percent} className="h-1.5 w-32" />
              <span className="text-muted-foreground w-12 text-right font-mono text-xs">
                {epic.done}/{epic.total}
              </span>
            </Link>
          ))}
        </Card>
      </div>

      <div className="flex min-w-0 flex-col gap-6">
        <Card title="Details">
          <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-y-2.5 px-4 py-3 text-sm">
            <dt className="text-muted-foreground">Key</dt>
            <dd className="font-mono">{project?.key}</dd>
            <dt className="text-muted-foreground">Started from</dt>
            <dd>{project ? PROJECT_SOURCE_LABELS[project.source] : ""}</dd>
            {project?.repo_url && (
              <>
                <dt className="text-muted-foreground">Repository</dt>
                <dd className="truncate font-mono text-xs leading-5">{project.repo_url.replace(/^https?:\/\//, "")}</dd>
              </>
            )}
            <dt className="text-muted-foreground">Who can see</dt>
            <dd>{project?.access === "restricted" ? "Only people added" : `Everyone in ${workspace?.name ?? "the workspace"}`}</dd>
            <dt className="text-muted-foreground">Agent model</dt>
            <dd className="truncate font-mono text-xs leading-5">{modelName(project?.model) || "Default"}</dd>
          </dl>
        </Card>

        <Card
          title="Summary"
          action={
            <Button size="xs" variant="outline" asChild>
              <Link href={chat.href}>
                <MessageSquareIcon />
                Ask Chat
              </Link>
            </Button>
          }
        >
          <p className="text-muted-foreground px-4 py-3 text-sm">
            Ask the team in Chat for a summary of what changed, what&apos;s blocked, and what&apos;s due.
          </p>
        </Card>

        <Card
          title="Recent activity"
          action={
            <Link href={`${base}/activity`} className="text-primary text-xs font-medium hover:underline">
              View all
            </Link>
          }
        >
          <div className="px-4">
            {activity.isLoading && <Skeleton className="my-3 h-24" />}
            {activity.data && activity.data.pages[0]?.length === 0 && (
              <p className="text-muted-foreground py-6 text-sm">Nothing yet.</p>
            )}
            {activity.data && workspace && (
              <ActivityFeed items={activity.data.pages[0] ?? []} members={memberMap} workspaceSlug={workspace.slug} compact />
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
