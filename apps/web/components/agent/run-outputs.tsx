import type { Schemas } from "@dotrix/api-client";
import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { Input } from "@dotrix/ui/components/input";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckIcon, CircleDotIcon, ExternalLinkIcon, FileTextIcon, GavelIcon, ListChecksIcon, TriangleAlertIcon, UndoIcon, XIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { agentKeys, useSendMessage, type AgentId, type Run } from "@/lib/agent";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useCreateIssue, type Scope } from "@/lib/issues";
import { can } from "@/lib/labels";
import { useWorkspaceProject } from "@/lib/queries";

type Output = Schemas["RunOutputRead"];
type Item = Schemas["RunOutputItem"];
type Source = Schemas["SourceRead"];

const CHECK_LABELS: Record<Schemas["ClaimCheck"]["status"], { label: string; variant: "secondary" | "outline" }> = {
  supported: { label: "Supported", variant: "secondary" },
  weak: { label: "Weak support", variant: "outline" },
  unsupported: { label: "No quote found", variant: "outline" },
};

const TIER_LABELS: Record<Source["tier"], string> = { primary: "Primary", reputable: "Reputable", other: "Other" };

/** What a research claim can turn into, asked of another agent in the same conversation. */
const ASK: Record<string, { agent: AgentId; label: string; icon: React.ReactNode; message: (claim: string, cites: string) => string }> = {
  propose_change: {
    agent: "product",
    label: "Propose a requirement change",
    icon: <ListChecksIcon />,
    message: (claim, cites) =>
      `Propose a change to the requirements based on this research finding: "${claim}"${cites}. Say which requirement it affects and why.`,
  },
  record_decision: {
    agent: "documentation",
    label: "Record a decision",
    icon: <GavelIcon />,
    message: (claim, cites) =>
      `Draft a decision record (ADR) for this research finding: "${claim}"${cites}. Include the context, the decision, and its consequences.`,
  },
};

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
      return {
        title: s("title"),
        body: [s("detail"), s("suggested_fix") && `Fix: ${s("suggested_fix")}`].filter(Boolean).join("\n\n"),
        tag: s("severity"),
        refs: list("refs"),
      };
    case "impact":
      return { title: s("ref"), body: s("why"), tag: s("severity") };
    case "report": {
      const quotes = Array.isArray(data.quotes) ? (data.quotes as { source?: string; text?: string }[]) : [];
      const body = quotes
        .filter((q) => q.text)
        .map((q) => `“${q.text}”${q.source ? ` [${String(q.source).replace(/^\[|\]$/g, "")}]` : ""}`)
        .join("\n");
      return { title: s("claim"), body, tag: s("confidence") && `${s("confidence")} confidence`, refs: list("sources") };
    }
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

/** A run's structured result: each item with what people did with it, and actions on the open
 * ones; then the web pages its agents found or read, which research claims cite. */
export function RunOutputs({ run, scope, canAct }: { run: Run; scope: Scope; canAct: boolean }) {
  const outputs = run.outputs ?? [];
  const sources = run.sources ?? [];
  if (outputs.length === 0 && sources.length === 0) return null;
  return (
    <div className="grid gap-3">
      {outputs.map((output) => (
        <OutputView key={output.id} run={run} output={output} scope={scope} canAct={canAct} />
      ))}
      {sources.length > 0 && <SourceList sources={sources} />}
    </div>
  );
}

function OutputView({ run, output, scope, canAct }: { run: Run; output: Output; scope: Scope; canAct: boolean }) {
  const report = output.kind === "report";
  // Research claims no quote was found for are assumptions, not findings.
  const assumption = (item: Item) => report && item.check?.status === "unsupported";
  const findings = output.items.filter((item) => !assumption(item));
  const assumptions = output.items.filter(assumption);
  const list = (items: Item[]) => (
    <ul className="grid gap-2">
      {items.map((item) => (
        <ItemView key={item.index} run={run} output={output} item={item} scope={scope} canAct={canAct} />
      ))}
    </ul>
  );
  return (
    <section className="grid gap-2 rounded-xl border p-3" aria-label={KIND_TITLES[output.kind] ?? output.kind}>
      <h4 className="text-sm font-medium">
        {KIND_TITLES[output.kind] ?? output.kind}{" "}
        <span className="text-muted-foreground font-normal">
          · {output.items.filter((i) => i.state === "open").length} open of {output.items.length}
        </span>
      </h4>
      {list(findings)}
      {assumptions.length > 0 && (
        <section className="grid gap-2" aria-label="Assumptions">
          <h5 className="text-sm font-medium">Assumptions</h5>
          <p className="text-muted-foreground text-xs">No quote for these was found in the pages read.</p>
          {list(assumptions)}
        </section>
      )}
      {report && <SaveNote run={run} output={output} scope={scope} />}
    </section>
  );
}

/** "Save as research note" (people who may edit documents), or where it was saved. */
function SaveNote({ run, output, scope }: { run: Run; output: Output; scope: Scope }) {
  const queryClient = useQueryClient();
  const { workspace, project } = useWorkspaceProject(scope.projectId);
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/outputs/{output_id}/note", {
          params: { path: { workspace_id: scope.workspaceId, project_id: scope.projectId, run_id: run.id, output_id: output.id } },
        }),
      ),
    onSuccess: () => toast.success("Saved as a research note"),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: agentKeys.project(scope) }),
  });
  const canSave = can(workspace, "knowledge:write");
  if (!output.note && !canSave) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {output.note && workspace && project && (
        <Link
          href={`/w/${workspace.slug}/p/${project.key}/knowledge?file=${encodeURIComponent(output.note)}`}
          className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
        >
          <FileTextIcon className="size-3.5" />
          Saved to {output.note}
        </Link>
      )}
      {canSave && (
        <Button size="sm" variant="outline" disabled={save.isPending} onClick={() => save.mutate()}>
          <FileTextIcon />
          {output.note ? "Save again" : "Save as research note"}
        </Button>
      )}
    </div>
  );
}

/** The run's web sources by id, with how far each can be trusted. */
function SourceList({ sources }: { sources: Source[] }) {
  return (
    <section className="grid gap-2 rounded-xl border p-3" aria-label="Sources">
      <h4 className="text-sm font-medium">Sources</h4>
      <ol className="grid gap-1.5 text-sm">
        {sources.map((source) => (
          <li key={source.label} className="grid gap-0.5">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-muted-foreground font-mono text-xs">[{source.label}]</span>
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="inline-flex min-w-0 items-center gap-1 break-all underline-offset-2 hover:underline"
              >
                {source.title || source.url}
                <ExternalLinkIcon className="size-3 shrink-0" />
              </a>
              <Badge variant={source.tier === "other" ? "outline" : "secondary"}>{TIER_LABELS[source.tier]}</Badge>
            </div>
            <p className="text-muted-foreground text-xs">
              {[
                source.host,
                source.published && `published ${source.published.slice(0, 10)}`,
                source.kind === "page" ? "read in full" : "seen in search results",
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {source.flagged.length > 0 && (
              <p className="bg-warning-muted flex items-center gap-1 rounded px-1.5 py-0.5 text-xs">
                <TriangleAlertIcon className="size-3.5 shrink-0" />
                This page addressed AI agents ({source.flagged.join(", ")}); its instructions were ignored.
              </p>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

function ItemView({ run, output, item, scope, canAct }: { run: Run; output: Output; item: Item; scope: Scope; canAct: boolean }) {
  const queryClient = useQueryClient();
  const createIssue = useCreateIssue(scope);
  const send = useSendMessage(scope);
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
        {item.check && <Badge variant={CHECK_LABELS[item.check.status].variant}>{CHECK_LABELS[item.check.status].label}</Badge>}
        <span className="font-medium">{title}</span>
      </div>
      {body && <p className="text-muted-foreground text-sm whitespace-pre-line">{body}</p>}
      {refs && refs.length > 0 && <p className="text-muted-foreground font-mono text-xs break-all">{refs.join(" · ")}</p>}
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
                const issue = (await createIssue.mutateAsync(issueFrom(output.kind, item.data, output.agent)).catch(() => null)) as Schemas["IssueRead"] | null;
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
          {Object.entries(ASK)
            .filter(([action]) => output.actions.includes(action))
            .map(([action, ask]) => (
              <Button
                key={action}
                size="sm"
                variant="outline"
                disabled={send.isPending || update.isPending}
                onClick={async () => {
                  const cites = refs?.length ? ` (sources ${refs.join(", ")}, from @${output.agent}'s report)` : "";
                  const sent = await send.mutateAsync({ message: ask.message(title, cites), threadId: run.thread_id, agent: ask.agent }).catch(() => null);
                  if (sent) update.mutate({ state: "done", link: `Asked @${ask.agent}` });
                }}
              >
                {ask.icon}
                {ask.label}
              </Button>
            ))}
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
