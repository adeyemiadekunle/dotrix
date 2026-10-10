import type { Schemas } from "@dotrix/api-client";
import { Button } from "@dotrix/ui/components/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@dotrix/ui/components/dialog";
import { Label } from "@dotrix/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@dotrix/ui/components/select";
import { Textarea } from "@dotrix/ui/components/textarea";
import { useState, type FormEvent } from "react";

import { Field, FormError, SubmitButton } from "@/components/form";
import { errorMessage } from "@/lib/api";
import { useCreateIssue, useEpics, useSimilarIssues, type IssueStatus, type IssueType, type Priority } from "@/lib/issues";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam } from "@/lib/url-state";

import { ISSUE_TYPES, PRIORITIES, PRIORITY_META, STATUS_META, TYPE_META, TypeIcon } from "./meta";

const NONE = "__none";

const DESCRIPTION_HINT: Partial<Record<IssueType, string>> = {
  story: "Acceptance criteria (required for stories)",
  bug: "Steps to reproduce, expected and actual behaviour (required for bugs)",
};

export function NewIssueDialog({
  open,
  onOpenChange,
  status = "todo",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The column it starts in (a board column's + button); To do otherwise. */
  status?: IssueStatus;
}) {
  const { scope } = useProjectScope();
  const epics = useEpics(scope);
  const create = useCreateIssue(scope);
  const [, openIssue] = useSearchParam("issue");
  const [type, setType] = useState<IssueType>("task");
  const [priority, setPriority] = useState<Priority>("medium");
  const [parent, setParent] = useState(NONE);
  const [description, setDescription] = useState("");
  const [title, setTitle] = useState("");
  const similar = useSimilarIssues(scope, title);
  const matches = title.trim().length >= 4 ? (similar.data ?? []) : [];

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: Schemas["IssueCreate"] = {
      type,
      status,
      title,
      priority,
      description,
      parent: parent === NONE || type === "epic" ? null : parent,
    };
    const issue = (await create.mutateAsync(body).catch(() => null)) as Schemas["IssueRead"] | null;
    if (issue) {
      onOpenChange(false);
      openIssue(issue.key);
    }
  }

  const needsDescription = type === "story" || type === "bug";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>New issue</DialogTitle>
            <DialogDescription>It starts in {STATUS_META[status].label}. You can set the rest once it&apos;s created.</DialogDescription>
          </DialogHeader>
          <FormError message={create.isError ? errorMessage(create.error) : null} />
          <Field
            label="Title"
            name="title"
            placeholder="Add a zone filter to the dispatch screen"
            required
            maxLength={200}
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            hint={
              matches.length > 0 ? (
                <span className="grid gap-1" aria-live="polite">
                  <span>Similar issues already exist. Is it one of these?</span>
                  {matches.map((m) => (
                    <button
                      key={m.ref}
                      type="button"
                      className="hover:text-foreground flex min-w-0 items-center gap-2 text-left"
                      onClick={() => {
                        onOpenChange(false);
                        openIssue(m.ref);
                      }}
                    >
                      <span className="font-mono">{m.ref}</span>
                      <span className="truncate underline-offset-2 hover:underline">{m.heading}</span>
                    </button>
                  ))}
                </span>
              ) : undefined
            }
          />
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label>Type</Label>
              <Select value={type} onValueChange={(v) => setType(v as IssueType)}>
                <SelectTrigger className="w-full" aria-label="Type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ISSUE_TYPES.filter((t) => t !== "sub-task").map((t) => (
                    <SelectItem key={t} value={t}>
                      <TypeIcon type={t} />
                      {TYPE_META[t].label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>Priority</Label>
              <Select value={priority} onValueChange={(v) => setPriority(v as Priority)}>
                <SelectTrigger className="w-full" aria-label="Priority">
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
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="new-issue-description">Description{needsDescription ? "" : " (optional)"}</Label>
            <Textarea
              id="new-issue-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={DESCRIPTION_HINT[type] ?? "Markdown supported"}
              required={needsDescription}
              rows={5}
            />
          </div>
          {type !== "epic" && (epics.data?.length ?? 0) > 0 && (
            <div className="grid gap-2">
              <Label>Epic</Label>
              <Select value={parent} onValueChange={setParent}>
                <SelectTrigger className="w-full" aria-label="Epic">
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
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={create.isPending}>Create issue</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
