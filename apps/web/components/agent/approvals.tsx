"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Input } from "@pmagent/ui/components/input";
import { cn } from "@pmagent/ui/lib/utils";
import { CheckIcon, ChevronDownIcon, ChevronRightIcon, Loader2Icon, ShieldCheckIcon, XIcon } from "lucide-react";
import { useState } from "react";

import { useDecide, type Approval, type Decision, type Run } from "@/lib/agent";
import type { Scope } from "@/lib/issues";

const TOOL_LABELS: Record<string, string> = {
  write_file: "Write file",
  edit_file: "Edit file",
  create_issue: "Create issue",
  update_issue: "Update issue",
  comment_issue: "Comment on issue",
};

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool.replaceAll("_", " ");
}

/** "/pmagent/roadmap.md" is shown as "roadmap.md": the knowledge root is implied. */
export function shortTarget(target: string | null): string | null {
  return target?.replace(/^\/pmagent\//, "") ?? null;
}

/** A unified diff, coloured by line. */
export function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="bg-muted/40 max-h-80 overflow-auto rounded-md border text-xs leading-relaxed">
      <code className="block min-w-fit p-2 font-mono">
        {diff.split("\n").map((line, i) => (
          <span
            key={i}
            className={cn(
              "block px-1 whitespace-pre",
              line.startsWith("+") && !line.startsWith("+++") && "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300",
              line.startsWith("-") && !line.startsWith("---") && "bg-red-500/15 text-red-800 dark:text-red-300",
              (line.startsWith("@@") || line.startsWith("+++") || line.startsWith("---")) && "text-muted-foreground",
            )}
          >
            {line || " "}
          </span>
        ))}
      </code>
    </pre>
  );
}

/** For actions that aren't file writes (issues, comments): the fields the agent wants to set. */
function ArgsView({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args).filter(([, v]) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length));
  return (
    <dl className="bg-muted/40 grid gap-1 rounded-md border p-2 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[6.5rem_1fr] gap-2">
          <dt className="text-muted-foreground">{key.replaceAll("_", " ")}</dt>
          <dd className="break-words whitespace-pre-wrap">
            {typeof value === "string" ? value : JSON.stringify(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

type Choice = { decision: Decision["decision"]; reason: string } | undefined;

function ApprovalCard({
  approval,
  choice,
  onChoose,
  canDecide,
  expanded: startExpanded,
}: {
  approval: Approval;
  choice: Choice;
  onChoose: (choice: Choice) => void;
  canDecide: boolean;
  expanded: boolean;
}) {
  const [expanded, setExpanded] = useState(startExpanded);
  const pending = approval.status === "pending";
  const target = shortTarget(approval.target);
  return (
    <div
      className={cn(
        "grid gap-2 rounded-lg border p-3 text-sm",
        pending && "border-warning/60 bg-warning-muted/40",
        choice?.decision === "approve" && "border-emerald-500/60",
        choice?.decision === "reject" && "border-red-500/60",
      )}
    >
      <button type="button" className="flex items-center gap-2 text-left" onClick={() => setExpanded((e) => !e)}>
        {expanded ? <ChevronDownIcon className="size-4 shrink-0" /> : <ChevronRightIcon className="size-4 shrink-0" />}
        <span className="font-medium">{toolLabel(approval.tool)}</span>
        {target && <code className="text-muted-foreground min-w-0 truncate font-mono text-xs">{target}</code>}
        <span className="flex-1" />
        {approval.status === "approved" && <Badge variant="secondary">Approved</Badge>}
        {approval.status === "rejected" && <Badge variant="outline">Rejected</Badge>}
      </button>
      {expanded && (approval.diff ? <DiffView diff={approval.diff} /> : <ArgsView args={approval.args} />)}
      {approval.status === "rejected" && approval.reason && (
        <p className="text-muted-foreground text-xs">Reason: {approval.reason}</p>
      )}
      {pending && canDecide && (
        <div className="grid gap-2">
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              variant={choice?.decision === "approve" ? "default" : "outline"}
              onClick={() => onChoose(choice?.decision === "approve" ? undefined : { decision: "approve", reason: "" })}
            >
              <CheckIcon />
              Approve
            </Button>
            <Button
              type="button"
              size="sm"
              variant={choice?.decision === "reject" ? "destructive" : "outline"}
              onClick={() => onChoose(choice?.decision === "reject" ? undefined : { decision: "reject", reason: "" })}
            >
              <XIcon />
              Reject
            </Button>
          </div>
          {choice?.decision === "reject" && (
            <Input
              value={choice.reason}
              onChange={(e) => onChoose({ decision: "reject", reason: e.target.value })}
              placeholder="Why? The agent sees this (optional)"
              maxLength={500}
              className="h-8"
              autoFocus
            />
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The actions a run is waiting on. Every pending action needs a decision, and they're sent
 * together (the run resumes once, with all of them).
 */
export function RunApprovals({ run, scope, canDecide }: { run: Run; scope: Scope; canDecide: boolean }) {
  const decide = useDecide(scope);
  const approvals = run.approvals ?? [];
  const pending = approvals.filter((a) => a.status === "pending");
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const decided = pending.filter((a) => choices[a.id]).length;

  function submit(all?: Decision["decision"]) {
    const decisions: Decision[] = pending.map((a) => {
      const choice = all ? { decision: all, reason: "" } : choices[a.id]!;
      return { approval_id: a.id, decision: choice.decision, reason: choice.reason.trim() || null };
    });
    decide.mutate({ runId: run.id, decisions });
  }

  if (approvals.length === 0) return null;
  return (
    <div className="grid gap-2">
      {pending.length > 0 && (
        <p className="text-warning-foreground flex items-center gap-1.5 text-xs font-medium">
          <ShieldCheckIcon className="size-3.5" />
          {pending.length === 1 ? "1 change waits for your approval" : `${pending.length} changes wait for your approval`}
          {!canDecide && " (you can't approve in this workspace)"}
        </p>
      )}
      {approvals.map((approval) => (
        <ApprovalCard
          key={approval.id}
          approval={approval}
          choice={choices[approval.id]}
          onChoose={(choice) => setChoices((c) => ({ ...c, [approval.id]: choice }))}
          canDecide={canDecide && !decide.isPending}
          expanded={approval.status === "pending" && pending.length <= 3}
        />
      ))}
      {pending.length > 0 && canDecide && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={decided < pending.length || decide.isPending} onClick={() => submit()}>
            {decide.isPending && <Loader2Icon className="animate-spin" />}
            {pending.length === 1 ? "Send decision" : `Send ${decided}/${pending.length} decisions`}
          </Button>
          {pending.length > 1 && (
            <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => submit("approve")}>
              Approve all
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
