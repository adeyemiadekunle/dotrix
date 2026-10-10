import type { Schemas } from "@dotrix/api-client";
import { Button } from "@dotrix/ui/components/button";
import { Input } from "@dotrix/ui/components/input";
import { Label } from "@dotrix/ui/components/label";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { Textarea } from "@dotrix/ui/components/textarea";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlusIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { SaveBar } from "@/components/form";
import { api, errorMessage, unwrap } from "@/lib/api";

type Skill = Schemas["WorkspaceSkillRead"];

const NAME = /^[a-z][a-z0-9-]{1,39}$/;
const NEW_SKILL = "Description: What it's for, in a sentence (agents see this line).\n\n## Steps\n1. …\n";

/** Settings → Agents: skills every project's agents can use (a project's own of the same name wins). */
export function WorkspaceSkills({ workspaceId }: { workspaceId: string }) {
  const skills = useQuery({
    queryKey: ["workspace-skills", workspaceId],
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/skills", { params: { path: { workspace_id: workspaceId } } })),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const current = skills.data?.find((s) => s.name === selected);

  return (
    <section className="grid gap-3">
      <div className="grid gap-1">
        <h2 className="font-semibold">Skills for every project</h2>
        <p className="text-muted-foreground text-sm">
          Procedures agents follow for a kind of work, like writing a release note. Agents see each skill&apos;s description and read the steps when the work
          calls for it. A project&apos;s own skill of the same name, in agent-rules/skills/, wins.
        </p>
      </div>
      {skills.isLoading ? (
        <Skeleton className="h-32" />
      ) : (
        <div className="grid gap-4 @2xl:grid-cols-[14rem_minmax(0,1fr)]">
          <div className="grid content-start gap-2">
            <ul className="grid gap-0.5" aria-label="Workspace skills">
              {skills.data?.map((s) => (
                <li key={s.name}>
                  <button
                    type="button"
                    onClick={() => setSelected(s.name)}
                    aria-current={selected === s.name}
                    className="hover:bg-muted aria-[current=true]:bg-muted grid w-full rounded-md px-2 py-1.5 text-left"
                  >
                    <span className="font-mono text-xs">{s.name}</span>
                    <span className="text-muted-foreground truncate text-xs">{s.description}</span>
                  </button>
                </li>
              ))}
              {skills.data?.length === 0 && <li className="text-muted-foreground text-xs">No shared skills yet.</li>}
            </ul>
            <form
              className="flex gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (NAME.test(newName)) {
                  setSelected(newName);
                  setNewName("");
                }
              }}
            >
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value.toLowerCase())}
                placeholder="new-skill-name"
                aria-label="New skill's name"
                className="h-8 font-mono text-xs"
              />
              <Button type="submit" size="icon" variant="outline" className="size-8" disabled={!NAME.test(newName)} aria-label="Add skill">
                <PlusIcon />
              </Button>
            </form>
          </div>
          {selected ? (
            <SkillEditor
              key={`${selected}-${current?.version ?? 0}`}
              workspaceId={workspaceId}
              name={selected}
              skill={current}
              onRemoved={() => setSelected(null)}
            />
          ) : (
            <p className="text-muted-foreground text-sm">Pick a skill to edit it, or name a new one.</p>
          )}
        </div>
      )}
    </section>
  );
}

function SkillEditor({ workspaceId, name, skill, onRemoved }: { workspaceId: string; name: string; skill: Skill | undefined; onRemoved: () => void }) {
  const queryClient = useQueryClient();
  const [content, setContent] = useState(skill?.content ?? NEW_SKILL);
  const save = useMutation({
    mutationFn: (text: string) =>
      unwrap(
        api.PUT("/v1/workspaces/{workspace_id}/skills/{name}", {
          params: { path: { workspace_id: workspaceId, name } },
          body: { content: text, base_version: skill?.version ?? 0 },
        }),
      ),
    onSuccess: (_saved, text) => {
      toast.success(text.trim() ? "Skill saved" : "Skill removed");
      void queryClient.invalidateQueries({ queryKey: ["workspace-skills", workspaceId] });
      if (!text.trim()) onRemoved();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate(content);
  }

  return (
    <form onSubmit={submit} className="grid content-start gap-2">
      <div className="flex items-center gap-2">
        <Label className="font-mono text-xs">{name}</Label>
        {skill && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive ml-auto h-7"
            disabled={save.isPending}
            onClick={() => save.mutate("")}
          >
            Remove
          </Button>
        )}
      </div>
      <Textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        rows={12}
        maxLength={20_000}
        className="font-mono text-xs"
        aria-label={`Skill ${name}`}
      />
      <SaveBar dirty={content !== (skill?.content ?? "")} pending={save.isPending} onDiscard={() => setContent(skill?.content ?? NEW_SKILL)} />
    </form>
  );
}
