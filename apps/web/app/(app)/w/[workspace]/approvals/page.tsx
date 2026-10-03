"use client";

import { Avatar, AvatarFallback } from "@pmagent/ui/components/avatar";
import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import {
  ArrowLeftIcon,
  AtSignIcon,
  BellIcon,
  BotIcon,
  CheckCheckIcon,
  CircleCheckIcon,
  CircleUserIcon,
  EyeIcon,
  ListChecksIcon,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo } from "react";

import { agentName } from "@/components/activity-feed";
import { RunApprovals } from "@/components/agent/approvals";
import { PageHeader } from "@/components/app-shell";
import { RunCard } from "@/components/coding/coding-run";
import { timeAgo } from "@/components/issues/issue-activity";
import type { MemberMap } from "@/components/issues/meta";
import { ProjectTile } from "@/components/project-tile";
import { EmptyState, NotFound } from "@/components/states";
import { useWorkspaceApprovals, type Run } from "@/lib/agent";
import { sessionHref, useCodingRun } from "@/lib/coding";
import { useMembers } from "@/lib/issues";
import { can } from "@/lib/labels";
import {
  useMarkRead,
  useNotificationCounts,
  useNotifications,
  type Notification,
  type NotificationKind,
} from "@/lib/notifications";
import { useCurrentWorkspace } from "@/lib/queries";
import { useSearchParam, useSetSearchParams } from "@/lib/url-state";

const TABS: { id: string; label: string; kinds?: NotificationKind[] }[] = [
  { id: "all", label: "All" },
  { id: "approvals", label: "Approvals", kinds: ["approval", "checkpoint", "decided"] },
  { id: "mentions", label: "Mentions", kinds: ["mention"] },
  { id: "assigned", label: "Issues", kinds: ["assigned", "watching"] },
  { id: "findings", label: "Findings", kinds: ["finding"] },
];

const isDecision = (n: Notification) => n.kind === "approval" || n.kind === "checkpoint";

/** Approvals and checkpoints need you until they're decided; the rest until you've read them. */
const needsYou = (n: Notification) => (isDecision(n) ? !n.resolved : !n.read);

function actorName(n: Notification, members: MemberMap): string {
  if (n.actor_agent) return agentName(n.actor_agent);
  if (n.actor_user_id) return members.get(n.actor_user_id)?.display_name ?? "Someone";
  return "Someone";
}

/** One line on what it is: "Project manager wants to make 2 changes". */
function headline(n: Notification, members: MemberMap): string {
  const who = actorName(n, members);
  if (n.coding_run_id) {
    // A coding run: the person asked a coding tool to code an issue.
    const person = n.actor_user_id ? (members.get(n.actor_user_id)?.display_name ?? "Someone") : "Someone";
    const tool = n.actor_agent ? agentName(n.actor_agent) : "the coding agent";
    if (n.kind === "approval") return `${person} asked ${tool} to code ${n.issue_key ?? "an issue"}`;
    if (n.kind === "decided") return `${who} decided the coding run you asked for`;
  }
  switch (n.kind) {
    case "approval":
      return n.count === 1 ? `${who} wants to make a change` : `${who} wants to make ${n.count} changes`;
    case "checkpoint":
      return `${who} wants you to check its plan`;
    case "assigned":
      return `${who} assigned you ${n.issue_key ?? "an issue"}`;
    case "finding":
      return n.count === 1 ? `${who} found something to look at` : `${who} found ${n.count} things to look at`;
    case "mention":
      return n.issue_key ? `${who} mentioned you on ${n.issue_key}` : `${who} mentioned you in Chat`;
    case "decided":
      return `${who} decided the changes you asked for`;
    case "watching":
      return `${who} on ${n.issue_key ?? "an issue"} you watch`;
  }
}

function conversationHref(slug: string, n: Notification): string {
  return `/w/${slug}/chat?project=${n.project_key}${n.thread_id ? `&thread=${n.thread_id}` : ""}`;
}

function NotificationIcon({ n }: { n: Notification }) {
  const Icon =
    n.kind === "assigned" ? CircleUserIcon : n.kind === "watching" ? EyeIcon : n.kind === "finding" ? ListChecksIcon : n.kind === "mention" ? AtSignIcon : n.kind === "decided" ? CircleCheckIcon : BotIcon;
  return (
    <Avatar className="size-7 rounded-lg">
      <AvatarFallback className="bg-brand-muted text-brand-muted-foreground rounded-lg">
        <Icon className="size-4" />
      </AvatarFallback>
    </Avatar>
  );
}

function Row({
  n,
  members,
  selected,
  onSelect,
}: {
  n: Notification;
  members: MemberMap;
  selected: boolean;
  onSelect: () => void;
}) {
  const unread = needsYou(n);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected || undefined}
      className={cn(
        "flex w-full items-start gap-3 border-b px-4 py-3 text-left text-sm last:border-b-0",
        selected ? "bg-muted" : "hover:bg-muted/60",
      )}
    >
      <NotificationIcon n={n} />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className={cn("truncate", unread && "font-semibold")}>{headline(n, members)}</span>
        <span className="text-muted-foreground truncate text-xs">{n.kind === "mention" && n.excerpt ? n.excerpt : n.title}</span>
        <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <ProjectTile projectKey={n.project_key} className="size-3.5 text-[7px]" />
          {n.project_name} · {timeAgo(n.created_at)}
          {n.resolved && " · Decided"}
        </span>
      </span>
      {unread && <span className="bg-primary mt-1.5 size-2 shrink-0 rounded-full" aria-label={isDecision(n) ? "Waiting" : "Unread"} />}
    </button>
  );
}

function Detail({
  n,
  members,
  workspace,
}: {
  n: Notification;
  members: MemberMap;
  workspace: NonNullable<ReturnType<typeof useCurrentWorkspace>["workspace"]>;
}) {
  const decision = isDecision(n);
  const approvals = useWorkspaceApprovals(workspace.id, decision && !n.resolved);
  const waiting = (approvals.data ?? []).filter((a) => a.run_id === n.run_id);
  const projectBase = `/w/${workspace.slug}/p/${n.project_key}`;
  return (
    <article className="flex flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-col gap-1">
        <span className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <ProjectTile projectKey={n.project_key} className="size-3.5 text-[7px]" />
          <Link href={projectBase} className="hover:underline">
            {n.project_name}
          </Link>
          · {new Date(n.created_at).toLocaleString()}
        </span>
        <h2 className="text-lg font-semibold">{headline(n, members)}</h2>
        <p className="text-muted-foreground text-sm">
          {n.kind === "assigned" || n.kind === "watching" || (n.kind === "mention" && n.issue_key) ? n.title : <>&ldquo;{n.title}&rdquo;</>}
        </p>
      </header>

      {n.kind === "decided" && n.excerpt && (
        <blockquote className="bg-muted/60 rounded-lg border-l-2 px-3 py-2 text-sm whitespace-pre-wrap">Why: {n.excerpt}</blockquote>
      )}

      {(n.kind === "mention" || n.kind === "watching") && n.excerpt && (
        <blockquote className="bg-muted/60 rounded-lg border-l-2 px-3 py-2 text-sm whitespace-pre-wrap">{n.excerpt}</blockquote>
      )}

      {n.coding_run_id && n.kind === "approval" && (
        <CodingApproval runId={n.coding_run_id} scope={{ workspaceId: workspace.id, projectId: n.project_id }} />
      )}
      {decision && n.resolved && !n.coding_run_id && (
        <p className="bg-muted rounded-lg px-3 py-2 text-sm">Decided. Nothing is waiting from this request now.</p>
      )}
      {decision && !n.resolved && approvals.isLoading && <Skeleton className="h-32" />}
      {decision && !n.resolved && waiting.length > 0 && (
        <RunApprovals
          // The approvals card works on a run; build the part of one it needs.
          run={{ id: n.run_id, requested_by_id: waiting[0]!.requested_by_id, approvals: waiting } as unknown as Run}
          scope={{ workspaceId: workspace.id, projectId: n.project_id }}
          canDecide={can(workspace, "agents:approve")}
        />
      )}

      <div className="flex flex-wrap gap-2">
        {(n.kind === "assigned" || n.kind === "mention" || n.kind === "watching") && n.issue_key && (
          <Button size="sm" asChild>
            <Link href={`${projectBase}/board?issue=${n.issue_key}`}>Open {n.issue_key}</Link>
          </Button>
        )}
        {n.coding_session_id && (
          <Button size="sm" variant={n.kind === "approval" ? "outline" : "default"} asChild>
            <Link href={sessionHref(workspace.slug, n.project_key, n.coding_session_id)}>Open the coding session</Link>
          </Button>
        )}
        {n.issue_key && n.coding_run_id && (
          <Button size="sm" variant="outline" asChild>
            <Link href={`${projectBase}/board?issue=${n.issue_key}`}>Open {n.issue_key}</Link>
          </Button>
        )}
        {n.run_id && (
          <Button size="sm" variant={n.kind === "finding" ? "default" : "outline"} asChild>
            <Link href={conversationHref(workspace.slug, n)}>Open the conversation</Link>
          </Button>
        )}
      </div>
    </article>
  );
}

/** A coding run waiting for approval: the run itself, with the brief, approve and reject. */
function CodingApproval({ runId, scope }: { runId: string; scope: { workspaceId: string; projectId: string } }) {
  const run = useCodingRun(scope, runId);
  if (run.isLoading) return <Skeleton className="h-32" />;
  if (!run.data) return null;
  return <RunCard run={run.data} issueKey={run.data.issue_key} scope={scope} />;
}

/** Notifications: what waits for you and what happened to you, with approvals decided in place. */
export default function NotificationsPage() {
  const { workspace, notFound } = useCurrentWorkspace();
  const [tabParam] = useSearchParam("tab");
  const [selectedId] = useSearchParam("n");
  const setParams = useSetSearchParams();
  const tab = TABS.find((t) => t.id === tabParam) ?? TABS[0]!;
  const notifications = useNotifications(workspace?.id);
  const counts = useNotificationCounts(workspace?.id);
  const markRead = useMarkRead(workspace?.id);
  const members = useMembers(workspace?.id);
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);

  const shown = useMemo(
    () => (notifications.data ?? []).filter((n) => !tab.kinds || tab.kinds.includes(n.kind)),
    [notifications.data, tab],
  );
  const selected = shown.find((n) => n.id === selectedId) ?? null;

  // Opening one marks it read.
  const { mutate } = markRead;
  useEffect(() => {
    if (selected && !selected.read) mutate({ ids: [selected.id], all: false });
  }, [selected, mutate]);

  if (notFound) return <NotFound what="workspace" />;
  const byKind = counts.data?.by_kind;
  const tabCount = (t: (typeof TABS)[number]) => (t.kinds ?? []).reduce((sum, k) => sum + (byKind?.[k] ?? 0), 0);
  const unread = counts.data?.unread ?? 0;
  // Marking read clears assignments and findings; approvals stay until someone decides them.
  const canMarkRead = shown.some((n) => !n.read && !isDecision(n));

  return (
    <>
      <PageHeader
        title="Notifications"
        parent={workspace?.name}
        actions={
          canMarkRead && (
            <Button
              size="sm"
              variant="outline"
              disabled={markRead.isPending}
              onClick={() => markRead.mutate({ all: true, kind: tab.kinds?.length === 1 ? tab.kinds[0] : null })}
            >
              <CheckCheckIcon />
              Mark all read
            </Button>
          )
        }
      />
      <div className="flex w-full max-w-6xl flex-col gap-4 p-4 md:p-6">
        <div role="tablist" aria-label="Show" className="bg-muted flex w-fit max-w-full gap-0.5 overflow-x-auto rounded-lg p-0.5 text-xs font-medium">
          {TABS.map((t) => {
            const count = t.id === "all" ? unread : tabCount(t);
            return (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab.id === t.id}
                onClick={() => setParams({ tab: t.id === "all" ? null : t.id, n: null })}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1",
                  tab.id === t.id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
                {count > 0 && <span className="text-primary tabular-nums">{count}</span>}
              </button>
            );
          })}
        </div>

        {notifications.isLoading && <Skeleton className="h-64" />}
        {notifications.data && shown.length === 0 && (
          <EmptyState
            icon={BellIcon}
            title="Nothing here"
            description="Changes the agents want to make, plans waiting for you, mentions, issues assigned to you, and agents' findings show up here."
          />
        )}
        {workspace && shown.length > 0 && (
          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
            <nav
              aria-label="Notifications"
              className={cn("bg-card overflow-hidden rounded-xl border", selected && "hidden lg:block")}
            >
              {shown.map((n) => (
                <Row
                  key={n.id}
                  n={n}
                  members={memberMap}
                  selected={n.id === selected?.id}
                  onSelect={() => setParams({ n: n.id })}
                />
              ))}
            </nav>
            <section className={cn("bg-card min-h-48 rounded-xl border", !selected && "hidden lg:block")}>
              {selected ? (
                <>
                  <Button variant="ghost" size="sm" className="m-2 lg:hidden" onClick={() => setParams({ n: null })}>
                    <ArrowLeftIcon />
                    All notifications
                  </Button>
                  <Detail key={selected.id} n={selected} members={memberMap} workspace={workspace} />
                </>
              ) : (
                <p className="text-muted-foreground p-6 text-sm">Pick a notification to see it here.</p>
              )}
            </section>
          </div>
        )}
      </div>
    </>
  );
}
