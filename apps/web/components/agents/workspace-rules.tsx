import type { Schemas } from "@dotrix/api-client";
import { Label } from "@dotrix/ui/components/label";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { Textarea } from "@dotrix/ui/components/textarea";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { SaveBar } from "@/components/form";
import { useAgents } from "@/lib/agents";
import { api, errorMessage, unwrap } from "@/lib/api";

type Rule = Schemas["WorkspaceRuleRead"];

/** Settings → Agents: rules every project's agents follow, for all of them or one agent. */
export function WorkspaceRules({ workspaceId }: { workspaceId: string }) {
  const rules = useQuery({
    queryKey: ["workspace-rules", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/rules", { params: { path: { workspace_id: workspaceId } } })),
  });
  const agents = useAgents({ workspaceId });
  const [handle, setHandle] = useState("base");
  const rule = rules.data?.find((r) => r.handle === handle);
  const configured = new Set(rules.data?.map((r) => r.handle));

  return (
    <section className="grid gap-3">
      <div className="grid gap-1">
        <h2 className="font-semibold">Rules for every project</h2>
        <p className="text-muted-foreground text-sm">
          Conventions every project&apos;s agents follow: how you write, what to always check, what never to do. Each
          project&apos;s own rules in agent-rules/ come after these, so a project can be more specific. What agents may
          never do is fixed in the platform and can&apos;t be changed here.
        </p>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="rules-for">For</Label>
        <select
          id="rules-for"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          className="bg-background h-9 w-fit rounded-md border px-2 text-sm"
        >
          <option value="base">Every agent{configured.has("base") ? " (set)" : ""}</option>
          {agents.data?.map((a) => (
            <option key={a.handle} value={a.handle}>
              {a.name}
              {configured.has(a.handle) ? " (set)" : ""}
            </option>
          ))}
        </select>
      </div>
      {rules.isLoading ? (
        <Skeleton className="h-40" />
      ) : (
        <RuleEditor key={`${handle}-${rule?.version ?? 0}`} workspaceId={workspaceId} handle={handle} rule={rule} />
      )}
    </section>
  );
}

function RuleEditor({ workspaceId, handle, rule }: { workspaceId: string; handle: string; rule: Rule | undefined }) {
  const queryClient = useQueryClient();
  const [content, setContent] = useState(rule?.content ?? "");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT("/v1/workspaces/{workspace_id}/rules/{handle}", {
          params: { path: { workspace_id: workspaceId, handle } },
          body: { content, base_version: rule?.version ?? 0 },
        }),
      ),
    onSuccess: () => {
      toast.success(content.trim() ? "Rules saved" : "Rules removed");
      void queryClient.invalidateQueries({ queryKey: ["workspace-rules", workspaceId] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const dirty = content !== (rule?.content ?? "");

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit} className="grid gap-2">
      <Textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={10}
        maxLength={20_000}
        className="font-mono text-xs"
        aria-label="Rules"
        placeholder={"- Write in British English.\n- Every story names the requirement it implements."}
      />
      {rule && <p className="text-muted-foreground text-xs">Version {rule.version}</p>}
      <SaveBar dirty={dirty} pending={save.isPending} onDiscard={() => setContent(rule?.content ?? "")} />
    </form>
  );
}
