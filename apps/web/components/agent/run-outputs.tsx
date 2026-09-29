"use client";

import type { Schemas } from "@pmagent/api-client";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Input } from "@pmagent/ui/components/input";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, CircleDotIcon, UndoIcon, XIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { agentKeys, type Run } from "@/lib/agent";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useCreateIssue, type Scope } from "@/lib/issues";

type Output = Schemas["RunOutputRead"];
type Item = Schemas["RunOutputItem"];

const KIND_TITLES: Record<string, string> = {
  finding: "Findings",
  plan: "Plan",
  spec: "Spec",
  impact: "What it affects",
  report: "Research findings",
  doc_update: "Documents to update",
  brief: "Coding brief",
};

const SEVERITY_TONE: Record<string, "destructive" | "secondary" | "outline"> = {
  critical: "destructive",
  high: "destructive",
  medium: "secondary",
  low: "outline",
};

/** The item's headline and body, by schema. */
function describe(kind: string, data: Record<string, unknown>): { title: string; body?: string; tag?: string; refs?: string[] } {
  const s = (key: string) => (typeof data[key] === "string" ? (data[key] as string) : "");
  const list = (key: string) => (Array.isArray(data[key]) ? (data[key] as unknown[]).map(String) : []);
  switch (kind) {
    case "finding":
      return { title: s("title"), body: [s("detail"), s("suggested_fix") && `Fix: ${s("suggested_fix")}`].filter(Boolean).join("\n\n"), tag: s("severity"), refs: list("refs") };
    case "impact":
      return { title: s("ref"), body: s("why"), tag: s("severity") };
    case "report":
      return { title: s("claim"), tag: s("confidence") && `${s("confidence")} confidence`, refs: list("sources") };
    case "plan":
      return { title: s("step"), body: s("expected_output"), tag: s("agent") && `@${s("agent")}` };
    case "doc_update":
      return { title: s("path"), body: s("reason") };
    case "spec":
      return { title: s("path"), body: s("summary") };
    case "brief":
      return { title: s("issue"), body: list("acceptance_criteria").join("\n") };
    default:
      return { title: JSON.stringify(data) };
  }
}

function issueFrom(kind: string, data: Record<string, unknown>, agent: string): Schemas["IssueCreate"] {
  const { title, body, refs } = describe(kind, data);
  const bug = kind === "finding";
  const lines = [body, refs?.length ? `Refs: ${refs.join(", ")}` : "", `From @${agent}'s ${kind}.`].filter(Boolean);
  return { type: bug ? "bug" : "task", title: title.slice(0, 200), description: lines.join("\n\n"), priority: "medium", status: "todo" };
}

/** A run's structured result: each item with what people did with it, and actions on the open ones. */
export function RunOutputs({ run, scope, canAct }: { run: Run; scope: Scope; canAct: boolean }) {
  const outputs = run.outputs ?? [];
  if (outputs.length === 0) return null;
  return (
    <div className="grid gap-3">
      {outputs.map((output) => (
        <OutputView key={output.id} run={run} output={output} scope={scope} canAct={canAct} />
      ))}
    </div>
  );
}

function OutputView({ run, output, scope, canAct }: { run: Run; output: Output; scope: Scope; canAct: boolean }) {
  return (
    <section className="grid gap-2 rounded-xl border p-3" aria-label={KIND_TITLES[output.kind] ?? output.kind}>
      <h4 className="text-sm font-medium">
        {KIND_TITLES[output.kind] ?? output.kind}{" "}
        <span className="text-muted-foreground font-normal">
          · {output.items.filter((i) => i.state === "open").length} open of {output.items.length}
        </span>
      </h4>
      <ul className="grid gap-2">
        {output.items.map((item) => (
          <ItemView key={item.index} run={run} output={output} item={item} scope={scope} canAct={canAct} />
        ))}
      </ul>
    </section>
  );
}

function ItemView({ run, output, item, scope, canAct }: { run: Run; output: Output; item: Item; scope: Scope; canAct: boolean }) {
  const queryClient = useQueryClient();
  const createIssue = useCreateIssue(scope);
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  const update = useMutation({
    mutationFn: (body: Schemas["OutputItemUpdate"]) =>
      unwrap(
        api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/outputs/{output_id}/items/{index}", {
          params: {
            path: { workspace_id: scope.workspaceId, project_id: scope.projectId, run_id: run.id, output_id: output.id, index: item.index },
          },
          body,
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: agentKeys.project(scope) }),
  });
  const { title, body, tag, refs } = describe(output.kind, item.data);
  const open = item.state === "open";

  return (
    <li className={open ? "grid gap-1.5" : "grid gap-1.5 opacity-70"}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {tag && <Badge variant={SEVERITY_TONE[tag] ?? "outline"}>{tag}</Badge>}
        <span className="font-medium">{title}</span>
      </div>
      {body && <p className="text-muted-foreground text-sm whitespace-pre-line">{body}</p>}
      {refs && refs.length > 0 && (
        <p className="text-muted-foreground font-mono text-xs break-all">{refs.join(" · ")}</p>
      )}
      {item.state === "done" && (
        <p className="flex items-center gap-1 text-xs">
          <CheckIcon className="size-3.5" /> Done{item.link ? `: ${item.link}` : ""}
        </p>
      )}
      {item.state === "dismissed" && (
        <p className="text-muted-foreground flex items-center gap-1 text-xs">
          <XIcon className="size-3.5" /> Dismissed{item.reason ? `: ${item.reason}` : ""}
        </p>
      )}
      {canAct && open && !dismissing && (
        <div className="flex flex-wrap gap-2">
          {output.actions.includes("create_issue") && (
            <Button
              size="sm"
              variant="outline"
              disabled={createIssue.isPending || update.isPending}
              onClick={async () => {
                const issue = (await createIssue
                  .mutateAsync(issueFrom(output.kind, item.data, output.agent))
                  .catch(() => null)) as Schemas["IssueRead"] | null;
                if (issue) {
                  update.mutate({ state: "done", link: issue.key });
                  toast.success(`Created ${issue.key}`);
                }
              }}
            >
              <CircleDotIcon />
              Create issue
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setDismissing(true)}>
            Dismiss
          </Button>
        </div>
      )}
      {canAct && dismissing && (
        <form
          className="flex gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            update.mutate({ state: "dismissed", reason: reason.trim() || null }, { onSuccess: () => setDismissing(false) });
          }}
        >
          <Input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why (optional)"
            aria-label="Why it's dismissed"
            maxLength={500}
            autoFocus
            className="h-8"
          />
          <Button type="submit" size="sm" disabled={update.isPending}>
            Dismiss
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setDismissing(false)}>
            Cancel
          </Button>
        </form>
      )}
      {canAct && !open && (
        <div>
          <Button size="sm" variant="ghost" className="h-7" disabled={update.isPending} onClick={() => update.mutate({ state: "open" })}>
            <UndoIcon />
            Reopen
          </Button>
        </div>
      )}
    </li>
  );
}
