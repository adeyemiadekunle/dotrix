import { Button } from "@dotrix/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@dotrix/ui/components/dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@/lib/navigation";
import { useState, type FormEvent } from "react";

import { Field, FormError, SubmitButton } from "@/components/form";
import { api, errorMessage, unwrap } from "@/lib/api";

/** An organisation is a workspace for a team: it invites people and holds many projects. */
export function CreateOrganizationDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (name: string) => unwrap(api.POST("/v1/workspaces", { body: { name, kind: "organization" } })),
    onSuccess: async (workspace) => {
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      onOpenChange(false);
      setName("");
      router.push(`/w/${workspace.slug}`);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-md">
        <form
          className="grid gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            create.mutate(name.trim());
          }}
        >
          <DialogHeader>
            <DialogTitle>Create an organisation</DialogTitle>
            <DialogDescription>
              A home for a team: invite people, give them roles, and run many projects together. You&apos;ll be its
              owner.
            </DialogDescription>
          </DialogHeader>
          <FormError message={create.isError ? errorMessage(create.error) : null} />
          <Field
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Kunemi Ltd"
            required
            maxLength={100}
            autoFocus
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={create.isPending}>Create organisation</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
