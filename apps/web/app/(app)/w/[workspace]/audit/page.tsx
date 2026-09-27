"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { BotIcon, CogIcon, ScrollTextIcon, UserIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { timeAgo } from "@/components/issues/issue-activity";
import { EmptyState, NotFound } from "@/components/states";
import { useAuditLog, type AuditEvent } from "@/lib/admin";
import { useMembers } from "@/lib/issues";
import { canManageProjects } from "@/lib/labels";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

const ANY = "__any";

/** What each recorded action means, in plain words (unknown ones show as recorded). */
const ACTIONS: Record<string, string> = {
  "knowledge.write": "changed a file",
  "knowledge.delete": "deleted a file",
  "approval.approved": "approved a change",
  "approval.rejected": "rejected a change",
  "agent_run.started": "started an agent run",
  "agent_run.awaiting_approval": "paused for approval",
  "agent_run.completed": "finished an agent run",
  "agent_run.failed": "had an agent run fail",
  "project.architecture_draft": "asked for an architecture draft",
  "issue.create": "created an issue",
  "issue.update": "updated an issue",
  "issue.claim": "claimed an issue",
};

const AGENTS: Record<string, string> = {
  "project-manager": "PM agent",
  "claude-code": "Claude Code",
  codex: "Codex",
  "coding-agent": "Coding agent",
};

function actorOf(e: AuditEvent, names: Map<string, string>): { who: string; kind: "user" | "agent" | "system" } {
  if (e.actor_type === "agent") {
    const agent = e.agent ?? "";
    const role = agent.replace(/-agent$/, "");
    const named = role ? `${role[0]!.toUpperCase()}${role.slice(1)} agent` : "An agent";
    return { who: AGENTS[agent] ?? named, kind: "agent" };
  }
  if (e.actor_type === "system") return { who: "pmagent", kind: "system" };
  return { who: (e.actor_user_id && names.get(e.actor_user_id)) || "Someone", kind: "user" };
}

function Event({
  event,
  names,
  projectKeys,
}: {
  event: AuditEvent;
  names: Map<string, string>;
  projectKeys: Map<string, string>;
}) {
  const actor = actorOf(event, names);
  const Icon = actor.kind === "agent" ? BotIcon : actor.kind === "system" ? CogIcon : UserIcon;
  const person = (id: string | null) => (id ? (names.get(id) ?? "a former member") : null);
  // A person's own edit records them as asker and approver too; that adds nothing here.
  const other = (id: string | null) => (id && id !== event.actor_user_id ? person(id) : null);
  const context = [
    other(event.instructed_by_id) && `asked by ${other(event.instructed_by_id)}`,
    other(event.approved_by_id) && `approved by ${other(event.approved_by_id)}`,
  ].filter(Boolean);
  const target = event.target && !/^[0-9a-f-]{36}$/.test(event.target) ? event.target : null;
  return (
    <li className="flex gap-3 p-3 text-sm">
      <Icon className={actor.kind === "agent" ? "text-brand mt-0.5 size-4 shrink-0" : "text-muted-foreground mt-0.5 size-4 shrink-0"} />
      <div className="grid min-w-0 flex-1 gap-0.5">
        <p className="min-w-0">
          <span className="font-medium">{actor.who}</span> {ACTIONS[event.action] ?? event.action}
          {target && (
            <>
              {" "}
              <code className="bg-muted rounded px-1 font-mono text-xs break-all">{target}</code>
            </>
          )}
        </p>
        {context.length > 0 && <p className="text-muted-foreground text-xs">{context.join(", ")}</p>}
      </div>
      <div className="grid shrink-0 justify-items-end gap-1">
        {event.project_id && projectKeys.get(event.project_id) && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {projectKeys.get(event.project_id)}
          </Badge>
        )}
        <time className="text-muted-foreground text-xs" dateTime={event.created_at} title={new Date(event.created_at).toLocaleString()}>
          {timeAgo(event.created_at)}
        </time>
      </div>
    </li>
  );
}

/** Every recorded change and agent action in the workspace, newest first (owners and admins). */
export default function AuditPage() {
  const { workspace, notFound } = useCurrentWorkspace();
  const allowed = canManageProjects(workspace?.role);
  const projects = useProjects(workspace?.id);
  const members = useMembers(workspace?.id);
  const [projectId, setProjectId] = useState<string>(ANY);
  const [action, setAction] = useState<string>(ANY);
  const log = useAuditLog(allowed ? workspace?.id : undefined, {
    projectId: projectId === ANY ? undefined : projectId,
    action: action === ANY ? undefined : action,
  });
  const names = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m.display_name])), [members.data]);
  const projectKeys = useMemo(() => new Map(projects.data?.map((p) => [p.id, p.key])), [projects.data]);
  const events = log.data?.pages.flat() ?? [];

  if (notFound) return <NotFound what="workspace" />;
  return (
    <>
      <PageHeader title="Audit log" parent={workspace?.name} />
      <div className="grid max-w-4xl content-start gap-4 p-4 md:p-6">
        {workspace && !allowed ? (
          <p className="text-muted-foreground text-sm">Only owners and admins see the audit log.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger size="sm" className="h-9 w-48" aria-label="Project">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>All projects</SelectItem>
                  {projects.data?.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      <span className="text-muted-foreground font-mono text-xs">{p.key}</span> {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={action} onValueChange={setAction}>
                <SelectTrigger size="sm" className="h-9 w-56" aria-label="Action">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY}>Every action</SelectItem>
                  {Object.entries(ACTIONS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label[0]!.toUpperCase() + label.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">Append-only: entries can&apos;t be edited or removed.</p>
            </div>
            {log.isLoading && <Skeleton className="h-64" />}
            {log.isSuccess && events.length === 0 && (
              <EmptyState
                icon={ScrollTextIcon}
                title="Nothing recorded yet"
                description="File changes, approvals, agent runs, and issue changes appear here as they happen."
              />
            )}
            {events.length > 0 && (
              <ol className="divide-y rounded-lg border">
                {events.map((e) => (
                  <Event key={e.id} event={e} names={names} projectKeys={projectKeys} />
                ))}
              </ol>
            )}
            {log.hasNextPage && (
              <Button variant="outline" className="justify-self-center" disabled={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>
                Load older entries
              </Button>
            )}
          </>
        )}
      </div>
    </>
  );
}
