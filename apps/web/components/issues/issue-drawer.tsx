"use client";

import type { Schemas } from "@pmagent/api-client";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Input } from "@pmagent/ui/components/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Separator } from "@pmagent/ui/components/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@pmagent/ui/components/sheet";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Textarea } from "@pmagent/ui/components/textarea";
import { cn } from "@pmagent/ui/lib/utils";
import { BellIcon, LinkIcon, PencilIcon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import {
  useComment,
  useEpics,
  useIssue,
  useMembers,
  useUpdateIssue,
  useWatch,
  type Issue,
  type Scope,
} from "@/lib/issues";
import { can } from "@/lib/labels";
import { useMe, useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

import { IssueActivity, timeAgo } from "./issue-activity";
import {
  AGENTS,
  AGENT_LABELS,
  ISSUE_TYPES,
  PRIORITIES,
  PRIORITY_META,
  STATUSES,
  STATUS_META,
  StatusIcon,
  TYPE_META,
  TypeIcon,
  type MemberMap,
} from "./meta";

const NONE = "__none";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid min-h-9 grid-cols-[5.5rem_minmax(0,1fr)] items-center gap-2 text-sm">
      <span className="text-muted-foreground pl-1">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

// Property controls read as plain values until you point at them, all one width.
const GHOST =
  "h-8 w-full border-transparent bg-transparent px-2 shadow-none hover:border-input focus-visible:border-ring dark:bg-transparent dark:hover:bg-input/30";

/** An input that saves when you leave it (or press Enter), if the value changed. */
function SaveOnBlur({
  value,
  onSave,
  disabled,
  ...props
}: { value: string; onSave: (value: string) => void; disabled?: boolean } & Omit<
  React.ComponentProps<typeof Input>,
  "value" | "defaultValue" | "onBlur"
>) {
  return (
    <Input
      key={value} // reset to the saved value when the issue refreshes
      defaultValue={value}
      disabled={disabled}
      className="h-8"
      onBlur={(e) => {
        if (e.target.value.trim() !== value) onSave(e.target.value.trim());
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") {
          e.currentTarget.value = value;
          e.currentTarget.blur();
        }
      }}
      {...props}
    />
  );
}

function KeyChips({ keys, onOpen }: { keys: string[]; onOpen: (key: string) => void }) {
  if (keys.length === 0) return <span className="text-muted-foreground">None</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {keys.map((key) => (
        <button key={key} type="button" onClick={() => onOpen(key)}>
          <Badge variant="outline" className="hover:bg-muted font-mono">
            {key}
          </Badge>
        </button>
      ))}
    </div>
  );
}

function Description({
  issue,
  canEdit,
  onSave,
}: {
  issue: Issue;
  canEdit: boolean;
  onSave: (description: string) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(issue.description);
  const [saving, setSaving] = useState(false);

  if (editing) {
    return (
      <div className="grid gap-2">
        <h3 className="text-sm font-semibold">Description</h3>
        <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={10} autoFocus maxLength={100_000} />
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSave(draft);
                setEditing(false);
              } finally {
                setSaving(false);
              }
            }}
          >
            Save
          </Button>
        </div>
      </div>
    );
  }
  return (
    <section className="grid gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Description</h3>
        {canEdit && (
          <Button
            size="xs"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() => {
              setDraft(issue.description);
              setEditing(true);
            }}
          >
            <PencilIcon />
            Edit
          </Button>
        )}
      </div>
      {issue.description ? (
        <Markdown>{issue.description}</Markdown>
      ) : (
        <p className="text-muted-foreground text-sm">
          {issue.type === "story" || issue.type === "bug"
            ? `No description yet. ${issue.type === "story" ? "Stories need acceptance criteria" : "Bugs need steps to reproduce"}.`
            : "No description yet."}
        </p>
      )}
    </section>
  );
}

function IssueDetails({
  issue,
  scope,
  members,
  canEdit,
  canAssignCodingAgent,
  onOpen,
}: {
  issue: Issue;
  scope: Scope;
  members: MemberMap;
  canEdit: boolean;
  canAssignCodingAgent: boolean;
  onOpen: (key: string) => void;
}) {
  const update = useUpdateIssue(scope);
  const comment = useComment(scope);
  const epics = useEpics(scope);
  const save = (changes: Schemas["IssueUpdate"]) => update.mutateAsync({ key: issue.key, changes });
  const assignee = issue.assignee_agent ?? issue.assignee_user_id ?? NONE;
  const reporter = issue.reporter_agent
    ? (AGENT_LABELS[issue.reporter_agent as keyof typeof AGENT_LABELS] ?? issue.reporter_agent)
    : issue.reporter_user_id
      ? (members.get(issue.reporter_user_id)?.display_name ?? "Former member")
      : "Unknown";

  return (
    <div className="grid [grid-template-areas:'title'_'props'_'body'] md:min-h-full md:grid-cols-[minmax(0,1fr)_18rem] md:grid-rows-[auto_1fr] md:[grid-template-areas:'title_props'_'body_props']">
      <div className="px-4 pt-1 pb-4 [grid-area:title] md:px-6">
        <SaveOnBlur
          value={issue.title}
          disabled={!canEdit}
          onSave={(title) => title && void save({ title })}
          aria-label="Title"
          className="-ml-2 h-auto border-transparent px-2 py-1 text-xl font-semibold tracking-tight shadow-none hover:border-input focus-visible:border-input md:text-xl dark:bg-transparent"
          maxLength={200}
        />
      </div>

      <aside
        aria-label="Properties"
        className="bg-muted/30 grid content-start gap-0.5 border-y px-3 py-3 [grid-area:props] md:border-y-0 md:border-l md:py-4"
      >
        <p className="text-muted-foreground px-1 pb-2 text-xs font-medium">Properties</p>
        <Field label="Status">
          <Select value={issue.status} disabled={!canEdit} onValueChange={(v) => void save({ status: v as Issue["status"] })}>
            <SelectTrigger aria-label="Status" size="sm" className={GHOST}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  <StatusIcon status={s} />
                  {STATUS_META[s].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Assignee">
          <Select
            value={assignee}
            disabled={!canEdit}
            onValueChange={(v) =>
              void save(
                v === NONE
                  ? { assignee_user_id: null, assignee_agent: null }
                  : AGENTS.includes(v as (typeof AGENTS)[number])
                    ? { assignee_agent: v as (typeof AGENTS)[number], assignee_user_id: null }
                    : { assignee_user_id: v, assignee_agent: null },
              )
            }
          >
            <SelectTrigger aria-label="Assignee" size="sm" className={GHOST}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Unassigned</SelectItem>
              <SelectGroup>
                <SelectLabel>People</SelectLabel>
                {[...members.values()].map((m) => (
                  <SelectItem key={m.user_id} value={m.user_id}>
                    {m.display_name}
                  </SelectItem>
                ))}
              </SelectGroup>
              <SelectGroup>
                <SelectLabel>Agents</SelectLabel>
                {AGENTS.map((a) => (
                  <SelectItem key={a} value={a} disabled={a === "coding-agent" && !canAssignCodingAgent}>
                    {AGENT_LABELS[a]}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Field label="Priority">
          <Select value={issue.priority} disabled={!canEdit} onValueChange={(v) => void save({ priority: v as Issue["priority"] })}>
            <SelectTrigger aria-label="Priority" size="sm" className={GHOST}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PRIORITIES.map((p) => {
                const meta = PRIORITY_META[p];
                return (
                  <SelectItem key={p} value={p}>
                    <meta.icon className={meta.className} />
                    {meta.label}
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Type">
          <Select value={issue.type} disabled={!canEdit} onValueChange={(v) => void save({ type: v as Issue["type"] })}>
            <SelectTrigger aria-label="Type" size="sm" className={GHOST}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ISSUE_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  <TypeIcon type={t} />
                  {TYPE_META[t].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {issue.type !== "epic" && (
          <Field label={issue.type === "sub-task" ? "Parent" : "Epic"}>
            {issue.type === "sub-task" ? (
              <SaveOnBlur
                value={issue.parent_key ?? ""}
                disabled={!canEdit}
                onSave={(v) => void save({ parent: v ? v.toUpperCase() : null })}
                placeholder="KEY-12"
                className={cn(GHOST, "font-mono uppercase")}
              />
            ) : (
              <Select
                value={issue.parent_key ?? NONE}
                disabled={!canEdit}
                onValueChange={(v) => void save({ parent: v === NONE ? null : v })}
              >
                <SelectTrigger aria-label="Epic" size="sm" className={GHOST}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>No epic</SelectItem>
                  {epics.data?.map((e) => (
                    <SelectItem key={e.key} value={e.key}>
                      <span className="text-muted-foreground font-mono text-xs">{e.key}</span> {e.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
        )}
        <Field label="Labels">
          <SaveOnBlur
            value={issue.labels.join(", ")}
            disabled={!canEdit}
            placeholder="frontend, payments"
            className={GHOST}
            onSave={(v) => void save({ labels: v.split(",").map((l) => l.trim()).filter(Boolean) })}
          />
        </Field>
        <Field label="Estimate">
          <SaveOnBlur
            value={issue.estimate?.toString() ?? ""}
            disabled={!canEdit}
            type="number"
            min={0}
            step="0.5"
            placeholder="Points or days"
            className={GHOST}
            onSave={(v) => void save({ estimate: v === "" ? null : Number(v) })}
          />
        </Field>
        <Field label="Due">
          <SaveOnBlur
            value={issue.due ?? ""}
            disabled={!canEdit}
            type="date"
            className={GHOST}
            onSave={(v) => void save({ due: v || null })}
          />
        </Field>
        <Field label="Depends on">
          {canEdit ? (
            <div className="grid gap-1.5">
              <SaveOnBlur
                value={(issue.depends_on ?? []).join(", ")}
                placeholder="KEY-3, KEY-7"
                className={cn(GHOST, "font-mono uppercase")}
                onSave={(v) =>
                  void save({ depends_on: v.split(",").map((k) => k.trim().toUpperCase()).filter(Boolean) })
                }
              />
              {(issue.depends_on?.length ?? 0) > 0 && <KeyChips keys={issue.depends_on ?? []} onOpen={onOpen} />}
            </div>
          ) : (
            <KeyChips keys={issue.depends_on ?? []} onOpen={onOpen} />
          )}
        </Field>
        <Field label="Blocks">
          <div className="px-2">
            <KeyChips keys={issue.blocks ?? []} onOpen={onOpen} />
          </div>
        </Field>
        {(issue.children?.length ?? 0) > 0 && (
          <Field label={issue.type === "epic" ? "Issues" : "Sub-tasks"}>
            <div className="px-2">
              <KeyChips keys={issue.children ?? []} onOpen={onOpen} />
            </div>
          </Field>
        )}
        <Separator className="my-2" />
        <Field label="Reporter">
          <span className="px-2">{reporter}</span>
        </Field>
        <Field label="Created">
          <span className="px-2" title={new Date(issue.created_at).toLocaleString()}>
            {timeAgo(issue.created_at)}
          </span>
          {issue.resolved_at && (
            <span className="text-muted-foreground"> · resolved {timeAgo(issue.resolved_at)}</span>
          )}
        </Field>
      </aside>

      <div className="grid content-start gap-6 px-4 pt-4 pb-8 [grid-area:body] md:px-6 md:pt-0">

        <Description key={issue.updated_at} issue={issue} canEdit={canEdit} onSave={(description) => save({ description })} />

        <Separator />

        <IssueActivity
          log={issue.log ?? []}
          members={members}
          canComment={canEdit}
          commenting={comment.isPending}
          onComment={(body) => comment.mutateAsync({ key: issue.key, body })}
        />
      </div>
    </div>
  );
}

/** Copy link and watch, in the drawer's header. */
function IssueActions({ issue, scope }: { issue: Issue; scope: Scope }) {
  const watch = useWatch(scope);
  const me = useMe();
  const watching = Boolean(me.data && issue.watchers?.includes(me.data.id));
  return (
    <div className="flex items-center gap-1">
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label="Copy link"
        title="Copy link"
        onClick={() => {
          void navigator.clipboard.writeText(window.location.href);
          toast.success("Link copied");
        }}
      >
        <LinkIcon />
      </Button>
      <Button
        size="sm"
        variant="outline"
        aria-pressed={watching}
        disabled={watch.isPending}
        onClick={() => watch.mutate({ key: issue.key, watch: !watching })}
        title={watching ? "Stop getting its changes" : "Get its changes"}
      >
        <BellIcon />
        {watching ? "Watching" : "Watch"}
      </Button>
    </div>
  );
}

/** The issue in `?issue=KEY`, in a panel over the board or backlog. */
export function IssueDrawer() {
  const [key, setKey] = useSearchParam("issue");
  const { workspace, scope, canEdit } = useProjectScope();
  const issue = useIssue(scope, key);
  const members = useMembers(workspace?.id);
  const memberMap: MemberMap = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m])), [members.data]);

  return (
    <Sheet open={Boolean(key)} onOpenChange={(open) => !open && setKey(null)}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-2xl lg:max-w-4xl">
        <SheetHeader className="bg-background sticky top-0 z-10 flex-row items-center gap-2 border-b py-3 pr-14 pl-4 md:pl-6">
          <SheetTitle className="flex flex-1 items-center gap-2 text-sm font-normal">
            {issue.data && <TypeIcon type={issue.data.type} />}
            <span className="text-muted-foreground font-mono">{key}</span>
            {issue.data && !issue.data.ready && issue.data.status === "todo" && (
              <Badge variant="outline" className="text-xs">
                Waiting on dependencies
              </Badge>
            )}
          </SheetTitle>
          {issue.data && scope && <IssueActions issue={issue.data} scope={scope} />}
          <SheetDescription className="sr-only">Issue details</SheetDescription>
        </SheetHeader>
        {issue.isLoading && (
          <div className="grid gap-4 p-4 md:px-6">
            <Skeleton className="h-8" />
            <Skeleton className="h-64" />
          </div>
        )}
        {issue.isError && (
          <p className="text-muted-foreground p-4 text-sm md:px-6">
            This issue doesn&apos;t exist, or it was moved. Check the key.
          </p>
        )}
        {issue.data && scope && (
          <IssueDetails
            issue={issue.data}
            scope={scope}
            members={memberMap}
            canEdit={canEdit}
            canAssignCodingAgent={can(workspace, "agents:code")}
            onOpen={setKey}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}
