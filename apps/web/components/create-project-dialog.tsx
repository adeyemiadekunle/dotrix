"use client";

import type { Schemas } from "@pmagent/api-client";
import { Button } from "@pmagent/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@pmagent/ui/components/dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Field, FormError, SubmitButton } from "@/components/form";
import { api, errorMessage, unwrap } from "@/lib/api";

/** Suggest a key from the name: initials of the words, or the first letters of one word. */
function suggestKey(name: string): string {
  const words = name.toUpperCase().match(/[A-Z0-9]+/g) ?? [];
  const key = words.length > 1 ? words.map((w) => w[0]).join("") : (words[0] ?? "").slice(0, 4);
  return key.replace(/^[0-9]+/, "").slice(0, 10);
}

export function CreateProjectDialog({
  workspace,
  open,
  onOpenChange,
}: {
  workspace: Schemas["WorkspaceWithRole"];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);

  const create = useMutation({
    mutationFn: (body: Schemas["ProjectCreate"]) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects", { params: { path: { workspace_id: workspace.id } }, body }),
      ),
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ["projects", workspace.id] });
      onOpenChange(false);
      setName("");
      setKey("");
      setKeyEdited(false);
      router.push(`/w/${workspace.slug}/p/${project.key}`);
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate({ name, key, description: String(form.get("description") ?? ""), source: "docs_only" });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              Starts from your docs. To use an existing repo, run <code className="font-mono">pmagent connect</code> in
              it.
            </DialogDescription>
          </DialogHeader>
          <FormError message={create.isError ? errorMessage(create.error) : null} />
          <Field
            label="Name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (!keyEdited) setKey(suggestKey(e.target.value));
            }}
            placeholder="Kumove"
            required
            maxLength={100}
            autoFocus
          />
          <Field
            label="Key"
            value={key}
            onChange={(e) => {
              setKey(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""));
              setKeyEdited(true);
            }}
            placeholder="KUN"
            required
            minLength={2}
            maxLength={10}
            pattern="[A-Z][A-Z0-9]{1,9}"
            className="font-mono uppercase"
            hint="Prefixes issue keys, like KUN-42. 2–10 letters or digits, starting with a letter; can't be changed."
          />
          <Field label="Description" name="description" placeholder="What the project is for" maxLength={500} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={create.isPending}>Create project</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
