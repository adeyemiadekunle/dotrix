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
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Field, SubmitButton } from "@/components/form";
import { useCreateOrg } from "@/lib/orgs";

export function CreateOrgDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const create = useCreateOrg();
  const [name, setName] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-md">
        <form
          className="grid gap-4"
          onSubmit={async (e: FormEvent) => {
            e.preventDefault();
            const org = await create.mutateAsync(name.trim()).catch(() => null);
            if (org) {
              onOpenChange(false);
              setName("");
              router.push(`/o/${org.slug}`);
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>Create an organisation</DialogTitle>
            <DialogDescription>
              An organisation owns several workspaces and manages people across them. You&apos;ll be its owner, and see
              every workspace it owns.
            </DialogDescription>
          </DialogHeader>
          <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Kunemi Ltd" required maxLength={100} autoFocus />
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
