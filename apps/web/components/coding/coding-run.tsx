"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@pmagent/ui/components/dialog";
import { Input } from "@pmagent/ui/components/input";
import { Label } from "@pmagent/ui/components/label";
import { Textarea } from "@pmagent/ui/components/textarea";
import { cn } from "@pmagent/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { CodeIcon, ExternalLinkIcon, GitBranchIcon, GitPullRequestIcon, Loader2Icon, MessageSquareIcon, SquareIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import {
  AGENT_NAMES,
  PR_LABELS,
  STATUS_LABELS,
  isActive,
  useCodingAvailability,
  useCodingRuns,
  useDecideCoding,
  useStartCoding,
  useStopCoding,
  type CodingRun,
} from "@/lib/coding";
import type { Issue, Scope } from "@/lib/issues";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

const STATUS_TONE: Partial<Record<CodingRun["status"], string>> = {
  awaiting_approval: "bg-warning-muted",
  running: "bg-brand-muted",
  queued: "bg-brand-muted",
  pr_opened: "bg-brand-muted",
};

/** "Start coding": ask for a coding run on this issue (it waits for an approval). */
export function StartCoding({ issue, scope }: { issue: Issue; scope: Scope }) {
  const availability = useCodingAvailability(scope);
  const runs = useCodingRuns(scope, issue.key);
  const start = useStartCoding(scope, issue.key);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const tool = availability.data?.agent ? AGENT_NAMES[availability.data.agent] : "the coding agent";
  // Hidden where the server doesn't run coding at all; disabled, with why, for anything a person can fix.
  if (!availability.data?.sandbox || issue.type === "epic" || issue.status === "done") return null;
  const busy = runs.data?.some(isActive);

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate(note.trim() || null, {
      onSuccess: (run) => {
        setOpen(false);
        setNote("");
        toast.success(run.can_decide ? "Waiting for your approval" : "Waiting for an owner or admin to approve it");
      },
    });
  }

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        disabled={!availability.data.available || busy}
        title={
          availability.data.reason ??
          (busy ? "A coding run is already waiting or working" : `${tool} codes it on a new branch and opens a PR`)
        }
        aria-label="Start coding"
        onClick={() => setOpen(true)}
      >
        <CodeIcon />
        <span className="hidden sm:inline">Start coding</span>
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <form onSubmit={submit} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Start coding {issue.key}</DialogTitle>
              <DialogDescription>
                {tool} works on a copy of the repository in a sandbox, from the issue, its acceptance criteria, and the
                documents it links to. The platform then pushes a new branch and opens a pull request; a person merges
                it. It starts once someone who may approve agent changes approves it.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-2">
              <Label htmlFor="coding-note">Anything to add (optional)</Label>
              <Textarea
                id="coding-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={5000}
                rows={4}
                placeholder="Where to start, what to leave alone, how to test it"
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={start.isPending}>
                {start.isPending && <Loader2Icon className="animate-spin" />}
                Ask for approval
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** "Implemented in PR #7" (or merged) once a coding session opened a PR for the issue. */
export function ImplementedIn({ issue, scope }: { issue: Issue; scope: Scope }) {
  const runs = useCodingRuns(scope, issue.key);
  const withPr = runs.data?.find((run) => run.pr_url);
  if (!withPr) return null;
  const merged = withPr.pr_state === "merged";
  return (
    <Badge variant="secondary" className={cn(merged ? "bg-brand-muted" : "bg-muted")} asChild>
      <a href={withPr.pr_url!} target="_blank" rel="noreferrer" title={withPr.branch ?? undefined}>
        <GitPullRequestIcon />
        {merged ? "Merged" : withPr.pr_state === "closed" ? "Closed" : "Implemented"} in PR #{withPr.pr_number}
      </a>
    </Badge>
  );
}

/** The issue's coding sessions: the latest turn in full, earlier sessions as a line each. */
export function CodingRuns({
  issue,
  scope,
  sessionLink,
}: {
  issue: Issue;
  scope: Scope;
  sessionLink?: (sessionId: string) => string;
}) {
  const runs = useCodingRuns(scope, issue.key);
  const queryClient = useQueryClient();
  const latest = runs.data?.[0];
  // When a run ends (a PR opened), the issue has moved to review: show it.
  const status = useRef(latest?.status);
  useEffect(() => {
    if (status.current && latest && status.current !== latest.status) {
      void queryClient.invalidateQueries({ queryKey: ["issues", scope.projectId] });
    }
    status.current = latest?.status;
  }, [latest, queryClient, scope.projectId]);

  if (!latest) return null;
  // Earlier sessions: the latest turn of each, newest first.
  const earlier = (runs.data ?? []).filter(
    (run, i, all) => run.session_id !== latest.session_id && all.findIndex((r) => r.session_id === run.session_id) === i,
  );
  return (
    <section className="grid gap-3" aria-label="Coding">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium">Coding</h3>
        {sessionLink && (
          <Button size="sm" variant="ghost" className="ml-auto h-7" asChild>
            <Link href={sessionLink(latest.session_id)}>
              <MessageSquareIcon />
              Open the session
            </Link>
          </Button>
        )}
      </div>
      <RunCard run={latest} issueKey={issue.key} scope={scope} label={latest.turn > 1 ? `Turn ${latest.turn}` : undefined} />
      {earlier.length > 0 && (
        <ul className="text-muted-foreground grid gap-1 text-xs">
          {earlier.map((run) => (
            <li key={run.id} className="flex items-center gap-2">
              {sessionLink ? (
                <Link href={sessionLink(run.session_id)} className="hover:underline">
                  {new Date(run.created_at).toLocaleString()}
                </Link>
              ) : (
                <span>{new Date(run.created_at).toLocaleString()}</span>
              )}
              <span>{STATUS_LABELS[run.status]}</span>
              {run.pr_url && (
                <a href={run.pr_url} target="_blank" rel="noreferrer" className="hover:underline">
                  PR #{run.pr_number}
                </a>
              )}
              {run.error && <span className="truncate">{run.error}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function RunCard({ run, issueKey, scope, label }: { run: CodingRun; issueKey: string; scope: Scope; label?: string }) {
  const decide = useDecideCoding(scope, issueKey);
  const stop = useStopCoding(scope, issueKey);
  // The Reviewer's conversation, in the workspace's Chat (RunCard also shows outside a project's pages).
  const { workspace } = useCurrentWorkspace();
  const projectKey = useProjects(workspace?.id).data?.find((p) => p.id === scope.projectId)?.key;
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const working = run.status === "running" || run.status === "queued";
  const tokens = run.input_tokens !== null && run.input_tokens !== undefined ? run.input_tokens + (run.output_tokens ?? 0) : null;

  return (
    <div className="grid gap-3 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {label && <span className="text-xs font-medium">{label}</span>}
        <Badge variant="secondary" className={cn(STATUS_TONE[run.status])}>
          {working && <Loader2Icon className="animate-spin" />}
          {STATUS_LABELS[run.status]}
        </Badge>
        <span className="text-muted-foreground text-xs">
          {AGENT_NAMES[run.agent]}
          {run.model ? ` (${run.model})` : ""} on {run.repo_full_name}
        </span>
        <div className="ml-auto flex gap-1">
          {run.pr_url && (
            <Button size="sm" variant="outline" asChild>
              <a href={run.pr_url} target="_blank" rel="noreferrer">
                <ExternalLinkIcon />
                PR #{run.pr_number}
                {run.pr_state && run.pr_state !== "open" && ` · ${PR_LABELS[run.pr_state]}`}
              </a>
            </Button>
          )}
          {run.review_thread_id && workspace && projectKey && (
            <Button size="sm" variant="ghost" asChild>
              <Link href={`/w/${workspace.slug}/chat?project=${projectKey}&thread=${run.review_thread_id}`}>
                <MessageSquareIcon />
                Reviewer
              </Link>
            </Button>
          )}
          {run.can_stop && (
            <Button size="sm" variant="ghost" disabled={stop.isPending} onClick={() => stop.mutate(run.id)}>
              <SquareIcon />
              {run.status === "running" ? "Stop" : "Cancel"}
            </Button>
          )}
        </div>
      </div>

      {run.branch && (
        <p className="text-muted-foreground flex items-center gap-1.5 font-mono text-xs">
          <GitBranchIcon className="size-3.5" />
          {run.branch}
          {run.files_changed.length > 0 && (
            <span className="font-sans">
              · {run.files_changed.length} file{run.files_changed.length === 1 ? "" : "s"} changed
            </span>
          )}
        </p>
      )}
      {run.error && <p className="text-destructive text-xs">{run.error}</p>}
      {run.decision_reason && run.status === "rejected" && (
        <p className="text-muted-foreground text-xs">Rejected: {run.decision_reason}</p>
      )}

      {run.events.length > 0 && <RunEvents events={run.events} live={working} />}
      {run.summary && (
        <div className="bg-muted/50 rounded-md p-2 text-sm">
          <Markdown>{run.summary}</Markdown>
        </div>
      )}

      <details className="text-xs">
        <summary className="text-muted-foreground cursor-pointer">What the agent is told</summary>
        <pre className="bg-muted mt-2 max-h-72 overflow-auto rounded-md p-2 whitespace-pre-wrap">{run.brief}</pre>
      </details>
      {tokens !== null && (run.started_at || tokens > 0) && (
        <p className="text-muted-foreground text-xs">
          {tokens.toLocaleString()} tokens{run.cost_usd ? ` · $${run.cost_usd.toFixed(2)}` : ""}
        </p>
      )}

      {run.status === "awaiting_approval" &&
        (run.can_decide ? (
          rejecting ? (
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                decide.mutate({ runId: run.id, decision: "reject", reason }, { onSuccess: () => setRejecting(false) });
              }}
            >
              <Input
                autoFocus
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why not (optional)"
                maxLength={1000}
                aria-label="Why not"
              />
              <Button type="submit" variant="destructive" size="sm" disabled={decide.isPending}>
                Reject
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setRejecting(false)}>
                Cancel
              </Button>
            </form>
          ) : (
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={decide.isPending}
                onClick={() => decide.mutate({ runId: run.id, decision: "approve" })}
              >
                {decide.isPending && <Loader2Icon className="animate-spin" />}
                Approve and start
              </Button>
              <Button size="sm" variant="outline" onClick={() => setRejecting(true)}>
                Reject
              </Button>
            </div>
          )
        ) : (
          <p className="text-muted-foreground text-xs">Waiting for an owner or admin to approve it.</p>
        ))}
    </div>
  );
}

function RunEvents({ events, live }: { events: CodingRun["events"]; live: boolean }) {
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (live && list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [events.length, live]);
  return (
    <ol ref={list} className="bg-muted/40 grid max-h-56 gap-1 overflow-y-auto rounded-md p-2 font-mono text-xs" aria-label="What the agent did">
      {events.map((event, i) => (
        <li
          key={i}
          className={cn(
            event.kind === "text" && "text-foreground font-sans",
            event.kind === "tool" && "text-muted-foreground",
            event.kind === "step" && "text-muted-foreground font-sans italic",
            event.kind === "error" && "text-destructive",
          )}
        >
          {event.text}
        </li>
      ))}
    </ol>
  );
}
