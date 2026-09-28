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
import { BellIcon, BellOffIcon, LinkIcon, PencilIcon } from "lucide-react";
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
  TYPE_META,
  TypeIcon,
  type MemberMap,
} from "./meta";

const NONE = "__none";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] items-center gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

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
    <div className="group relative">
      {issue.description ? (
        <Markdown>{issue.description}</Markdown>
      ) : (
        <p className="text-muted-foreground text-sm">
          {issue.type === "story" || issue.type === "bug"
            ? `No description yet. ${issue.type === "story" ? "Stories need acceptance criteria" : "Bugs need steps to reproduce"}.`
            : "No description yet."}
        </p>
      )}
      {canEdit && (
        <Button
          size="sm"
          variant="outline"
          className="mt-2"
          onClick={() => {
            setDraft(issue.description);
            setEditing(true);
          }}
        >
          <PencilIcon />
          Edit description
        </Button>
      )}
    </div>
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
  const watch = useWatch(scope);
  const epics = useEpics(scope);
  const me = useMe();
  const save = (changes: Schemas["IssueUpdate"]) => update.mutateAsync({ key: issue.key, changes });
  const watching = Boolean(me.data && issue.watchers?.includes(me.data.id));
  const assignee = issue.assignee_agent ?? issue.assignee_user_id ?? NONE;
  const reporter = issue.reporter_agent
    ? (AGENT_LABELS[issue.reporter_agent as keyof typeof AGENT_LABELS] ?? issue.reporter_agent)
    : issue.reporter_user_id
      ? (members.get(issue.reporter_user_id)?.display_name ?? "Former member")
      : "Unknown";

  return (
    <div className="grid gap-6 px-4 pb-8 md:px-6">
      <SaveOnBlur
        value={issue.title}
        disabled={!canEdit}
        onSave={(title) => title && void save({ title })}
        aria-label="Title"
        className="h-auto border-transparent px-2 py-1 text-lg font-semibold shadow-none hover:border-input focus-visible:border-input md:text-lg"
        maxLength={200}
      />

      <div className="grid gap-3">
        <Field label="Status">
          <Select value={issue.status} disabled={!canEdit} onValueChange={(v) => void save({ status: v as Issue["status"] })}>
            <SelectTrigger aria-label="Status" size="sm" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  <span className={cn("size-2 rounded-full", STATUS_META[s].dot)} />
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
            <SelectTrigger aria-label="Assignee" size="sm" className="w-44">
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
            <SelectTrigger aria-label="Priority" size="sm" className="w-44">
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
            <SelectTrigger aria-label="Type" size="sm" className="w-44">
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
                className="h-8 w-44 font-mono uppercase"
              />
            ) : (
              <Select
                value={issue.parent_key ?? NONE}
                disabled={!canEdit}
                onValueChange={(v) => void save({ parent: v === NONE ? null : v })}
              >
                <SelectTrigger aria-label="Epic" size="sm" className="w-full max-w-72">
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
            className="h-8 w-44"
            onSave={(v) => void save({ estimate: v === "" ? null : Number(v) })}
          />
        </Field>
        <Field label="Due">
          <SaveOnBlur
            value={issue.due ?? ""}
            disabled={!canEdit}
            type="date"
            className="h-8 w-44"
            onSave={(v) => void save({ due: v || null })}
          />
        </Field>
        <Field label="Depends on">
          {canEdit ? (
            <div className="grid gap-1.5">
              <SaveOnBlur
                value={(issue.depends_on ?? []).join(", ")}
                placeholder="KEY-3, KEY-7"
                className="h-8 font-mono uppercase"
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
          <KeyChips keys={issue.blocks ?? []} onOpen={onOpen} />
        </Field>
        {(issue.children?.length ?? 0) > 0 && (
          <Field label={issue.type === "epic" ? "Issues" : "Sub-tasks"}>
            <KeyChips keys={issue.children ?? []} onOpen={onOpen} />
          </Field>
        )}
        <Field label="Reporter">{reporter}</Field>
        <Field label="Created">
          <span title={new Date(issue.created_at).toLocaleString()}>{timeAgo(issue.created_at)}</span>
          {issue.resolved_at && (
            <span className="text-muted-foreground"> · resolved {timeAgo(issue.resolved_at)}</span>
          )}
        </Field>
      </div>

      <div className="flex gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            void navigator.clipboard.writeText(window.location.href);
            toast.success("Link copied");
          }}
        >
          <LinkIcon />
          Copy link
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={watch.isPending}
          onClick={() => watch.mutate({ key: issue.key, watch: !watching })}
        >
          {watching ? <BellOffIcon /> : <BellIcon />}
          {watching ? "Stop watching" : "Watch"}
        </Button>
      </div>

      <Separator />

      <section className="grid gap-2">
        <h3 className="text-sm font-medium">Description</h3>
        <Description key={issue.updated_at} issue={issue} canEdit={canEdit} onSave={(description) => save({ description })} />
      </section>

      <Separator />

      <IssueActivity
        log={issue.log ?? []}
        members={members}
        canComment={canEdit}
        commenting={comment.isPending}
        onComment={(body) => comment.mutateAsync({ key: issue.key, body })}
      />
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
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-xl">
        <SheetHeader className="px-4 md:px-6">
          <SheetTitle className="flex items-center gap-2 text-sm font-normal">
            {issue.data && <TypeIcon type={issue.data.type} />}
            <span className="text-muted-foreground font-mono">{key}</span>
            {issue.data && !issue.data.ready && issue.data.status === "todo" && (
              <Badge variant="outline" className="text-xs">
                Waiting on dependencies
              </Badge>
            )}
          </SheetTitle>
          <SheetDescription className="sr-only">Issue details</SheetDescription>
        </SheetHeader>
        {issue.isLoading && (
          <div className="grid gap-4 px-4 md:px-6">
            <Skeleton className="h-8" />
            <Skeleton className="h-64" />
          </div>
        )}
        {issue.isError && (
          <p className="text-muted-foreground px-4 text-sm md:px-6">
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
