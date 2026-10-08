import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Textarea } from "@pmagent/ui/components/textarea";
import { cn } from "@pmagent/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { CodeIcon, ExternalLinkIcon, GitBranchIcon, Loader2Icon, SendIcon, ShieldAlertIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { timeAgo } from "@/components/issues/issue-activity";
import { ProjectTile } from "@/components/project-tile";
import {
  AGENT_NAMES,
  PR_LABELS,
  STATUS_LABELS,
  isActive,
  useCodingSession,
  useFollowUp,
  type CodingSession,
} from "@/lib/coding";
import type { Scope } from "@/lib/issues";
import { can } from "@/lib/labels";

import { RunCard } from "./coding-run";

const ORIGIN_LABELS = {
  start: "Started from the issue",
  assigned: "Started when assigned",
  follow_up: "Follow-up",
} as const;

/** The workspace's coding sessions, grouped by project, for Chat's Coding tab. */
export function CodingSessionList({
  sessions,
  projects,
  selected,
  onOpen,
}: {
  sessions: CodingSession[];
  projects: { id: string; key: string; name: string }[];
  selected: string | null;
  onOpen: (session: CodingSession) => void;
}) {
  const byProject = new Map<string, CodingSession[]>();
  for (const session of sessions)
    byProject.set(session.project_id, [...(byProject.get(session.project_id) ?? []), session]);
  const withSessions = projects.filter((p) => byProject.has(p.id));
  if (withSessions.length === 0) {
    return (
      <p className="text-muted-foreground px-2 text-xs">
        No coding sessions yet. Start one from an issue (&ldquo;Start coding&rdquo;), or assign an issue to Claude Code
        or Codex.
      </p>
    );
  }
  return (
    <>
      {withSessions.map((p) => (
        <div key={p.id} className="grid gap-0.5 pb-2">
          <span className="flex items-center gap-1.5 px-1.5 py-1.5 text-sm font-medium">
            <ProjectTile projectKey={p.key} className="size-4 text-[8px]" />
            <span className="truncate">{p.name}</span>
          </span>
          {byProject.get(p.id)!.map((s) => (
            <button
              key={s.session_id}
              type="button"
              onClick={() => onOpen(s)}
              aria-current={s.session_id === selected ? "true" : undefined}
              className={cn(
                "hover:bg-muted grid w-full gap-0.5 rounded-md py-1.5 pr-2 pl-7 text-left text-sm",
                s.session_id === selected && "bg-muted",
              )}
            >
              <span className="flex items-center gap-1.5">
                {s.status === "awaiting_approval" && <ShieldAlertIcon className="text-warning size-3.5 shrink-0" />}
                {(s.status === "running" || s.status === "queued") && (
                  <Loader2Icon className="size-3.5 shrink-0 animate-spin" />
                )}
                <span className="text-muted-foreground shrink-0 font-mono text-xs">{s.issue_key}</span>
                <span className="truncate">{s.issue_title}</span>
              </span>
              <span className="text-muted-foreground truncate text-xs">
                {STATUS_LABELS[s.status]}
                {s.pr_number
                  ? ` · PR #${s.pr_number}${s.pr_state && s.pr_state !== "open" ? ` ${PR_LABELS[s.pr_state].toLowerCase()}` : ""}`
                  : ""}
                {s.turns > 1 ? ` · ${s.turns} turns` : ""} · {timeAgo(s.updated_at)}
              </span>
            </button>
          ))}
        </div>
      ))}
    </>
  );
}

/** One session: its turns, first to latest, and a follow-up for the same agent on its branch. */
export function CodingSessionView({
  scope,
  sessionId,
  summary,
  issueHref,
  canCode,
}: {
  scope: Scope;
  sessionId: string;
  summary: CodingSession | undefined;
  issueHref: string;
  canCode: boolean;
}) {
  const turns = useCodingSession(scope, sessionId);
  const queryClient = useQueryClient();
  const latest = turns.data?.at(-1);
  const issueKey = latest?.issue_key ?? summary?.issue_key ?? "";
  const followUp = useFollowUp(scope, sessionId, issueKey);
  const [message, setMessage] = useState("");
  const end = useRef<HTMLDivElement>(null);
  // A turn that ends moves the issue and the session list along.
  const status = useRef(latest?.status);
  useEffect(() => {
    if (status.current && latest && status.current !== latest.status) {
      void queryClient.invalidateQueries({ queryKey: ["coding-sessions"] });
      void queryClient.invalidateQueries({
        queryKey: ["issues", scope.projectId],
      });
    }
    status.current = latest?.status;
  }, [latest, queryClient, scope.projectId]);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [turns.data?.length]);

  if (turns.isLoading) {
    return (
      <div className="grid gap-3 p-4">
        <Skeleton className="h-8" />
        <Skeleton className="h-48" />
      </div>
    );
  }
  if (!turns.data?.length || !latest) {
    return (
      <p className="text-muted-foreground p-4 text-sm">
        This session doesn&apos;t exist, or you can&apos;t see its project.
      </p>
    );
  }
  const pr = [...turns.data].reverse().find((t) => t.pr_url);
  const busy = turns.data.some(isActive);

  function submit(event: FormEvent) {
    event.preventDefault();
    followUp.mutate(message.trim(), { onSuccess: () => setMessage("") });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2 text-sm">
        <CodeIcon className="text-muted-foreground size-4" />
        <Link href={issueHref} className="font-mono text-xs hover:underline">
          {issueKey}
        </Link>
        <span className="min-w-0 flex-1 truncate font-medium">{summary?.issue_title ?? ""}</span>
        <Badge variant="secondary">{AGENT_NAMES[latest.agent]}</Badge>
        {latest.branch && (
          <span className="text-muted-foreground flex items-center gap-1 font-mono text-xs">
            <GitBranchIcon className="size-3.5" />
            {latest.branch}
          </span>
        )}
        {pr && (
          <Button size="sm" variant="outline" className="h-7" asChild>
            <a href={pr.pr_url!} target="_blank" rel="noreferrer">
              <ExternalLinkIcon />
              PR #{pr.pr_number}
              {pr.pr_state ? ` · ${PR_LABELS[pr.pr_state]}` : ""}
            </a>
          </Button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto grid max-w-3xl gap-4 p-4">
          {turns.data.map((turn) => (
            <section key={turn.id} className="grid gap-2" aria-label={`Turn ${turn.turn}`}>
              {turn.note && (
                <div className="bg-muted ml-auto max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">
                  {turn.note}
                </div>
              )}
              <RunCard
                run={turn}
                issueKey={turn.issue_key}
                scope={scope}
                label={`Turn ${turn.turn} · ${ORIGIN_LABELS[turn.origin]} · ${timeAgo(turn.created_at)}`}
              />
            </section>
          ))}
          <div ref={end} />
        </div>
      </div>
      {canCode && (
        <form onSubmit={submit} className="border-t p-3">
          <div className="mx-auto grid max-w-3xl gap-2">
            <Textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && message.trim()) submit(e);
              }}
              disabled={busy}
              maxLength={5000}
              rows={3}
              aria-label="Follow-up"
              placeholder={
                busy
                  ? "A turn is waiting or working; follow up once it's done"
                  : `Ask ${AGENT_NAMES[latest.agent]} for more on ${latest.branch ?? "this issue"} (it waits for approval)`
              }
            />
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground text-xs">
                {pr ? `Pushes to PR #${pr.pr_number}.` : "Opens a PR when it changes something."} Ctrl+Enter to send
              </span>
              <Button
                type="submit"
                size="sm"
                className="ml-auto"
                disabled={busy || !message.trim() || followUp.isPending}
              >
                {followUp.isPending ? <Loader2Icon className="animate-spin" /> : <SendIcon />}
                Follow up
              </Button>
            </div>
          </div>
        </form>
      )}
    </div>
  );
}

/** Chat's Coding tab, right of the list: the open session, or what sessions are. */
export function CodingPane({
  workspace,
  projects,
  sessions,
  sessionId,
  onOpen,
  onConversations,
}: {
  workspace: { id: string; slug: string } & Parameters<typeof can>[0];
  projects: { id: string; key: string; name: string }[];
  sessions: CodingSession[];
  sessionId: string | null;
  onOpen: (session: CodingSession | null) => void;
  onConversations: () => void;
}) {
  const session = sessions.find((s) => s.session_id === sessionId);
  const project = session ? projects.find((p) => p.id === session.project_id) : undefined;
  return (
    <>
      <div className="flex h-11 shrink-0 items-center gap-2 border-b px-4">
        <span className="flex-1 text-sm font-medium">Coding</span>
        {/* Phones: the session list is a menu. */}
        <select
          aria-label="Coding session"
          value={sessionId ?? ""}
          onChange={(e) => onOpen(sessions.find((s) => s.session_id === e.target.value) ?? null)}
          className="bg-background h-7 max-w-44 rounded-md border px-1.5 text-xs md:hidden"
        >
          <option value="">Sessions</option>
          {sessions.map((s) => (
            <option key={s.session_id} value={s.session_id}>
              {s.issue_key} · {s.issue_title}
            </option>
          ))}
        </select>
        <Button size="sm" variant="ghost" className="md:hidden" onClick={onConversations}>
          Conversations
        </Button>
      </div>
      {sessionId && project ? (
        <CodingSessionView
          key={sessionId}
          scope={{ workspaceId: workspace.id, projectId: project.id }}
          sessionId={sessionId}
          summary={session}
          issueHref={`/w/${workspace.slug}/p/${project.key}/board?issue=${session?.issue_key ?? ""}`}
          canCode={can(workspace, "agents:code")}
        />
      ) : (
        <div className="grid flex-1 content-center justify-items-center gap-2 p-6 text-center">
          <p className="font-medium">Coding sessions</p>
          <p className="text-muted-foreground max-w-md text-sm">
            Each &ldquo;Start coding&rdquo; on an issue, or assigning an issue to Claude Code or Codex, starts a
            session: the agent codes it in a sandbox and the platform opens a PR. Open one to follow it, approve it, or
            ask for more on the same branch.
          </p>
        </div>
      )}
    </>
  );
}
