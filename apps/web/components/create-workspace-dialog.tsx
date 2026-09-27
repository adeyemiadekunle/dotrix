"use client";

import { Button } from "@pmagent/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@pmagent/ui/components/dialog";
import { Label } from "@pmagent/ui/components/label";
import { RadioGroup, RadioGroupItem } from "@pmagent/ui/components/radio-group";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Field, FormError, SubmitButton } from "@/components/form";
import { api, errorMessage, unwrap } from "@/lib/api";

const KINDS = [
  { value: "team", label: "Team", description: "A shared board and roles for a team." },
  { value: "business", label: "Business", description: "For a company; can belong to an organisation." },
] as const;

type Kind = (typeof KINDS)[number]["value"];

export function CreateWorkspaceDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<Kind>("team");
  const create = useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/v1/workspaces", { body: { name, kind } })),
    onSuccess: async (workspace) => {
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      onOpenChange(false);
      router.push(`/w/${workspace.slug}`);
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    create.mutate(String(new FormData(event.currentTarget).get("name")));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Create a workspace</DialogTitle>
            <DialogDescription>You&apos;ll be its owner, and can invite people once it&apos;s created.</DialogDescription>
          </DialogHeader>
          <FormError message={create.isError ? errorMessage(create.error) : null} />
          <Field label="Name" name="name" placeholder="Acme engineering" required maxLength={100} autoFocus />
          <RadioGroup value={kind} onValueChange={(v) => setKind(v as Kind)} className="grid gap-2">
            {KINDS.map((k) => (
              <Label
                key={k.value}
                className="has-[[data-state=checked]]:border-primary flex cursor-pointer items-start gap-3 rounded-md border p-3 font-normal"
              >
                <RadioGroupItem value={k.value} className="mt-0.5" />
                <span className="grid gap-1">
                  <span className="font-medium">{k.label}</span>
                  <span className="text-muted-foreground text-xs">{k.description}</span>
                </span>
              </Label>
            ))}
          </RadioGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={create.isPending}>Create workspace</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
