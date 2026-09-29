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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Field, FormError, SubmitButton } from "@/components/form";
import { CreateOrgDialog } from "@/components/orgs/create-org-dialog";
import { api, errorMessage, unwrap } from "@/lib/api";
import { useOrgs } from "@/lib/orgs";

/**
 * A new workspace always belongs to an organisation: only those can invite people (a personal
 * workspace is just for you). It lists the organisations you own or administer; with none,
 * it offers to create one first.
 */
export function CreateWorkspaceDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const orgs = useOrgs();
  const manageable = (orgs.data ?? []).filter((o) => o.role === "owner" || o.role === "admin");
  const [picked, setPicked] = useState<string | null>(null);
  const [creatingOrg, setCreatingOrg] = useState(false);
  const orgId = picked ?? manageable[0]?.id ?? null;
  const create = useMutation({
    mutationFn: (name: string) =>
      unwrap(
        api.POST("/v1/organizations/{org_id}/workspaces", {
          params: { path: { org_id: orgId! } },
          body: { name, kind: "team" },
        }),
      ),
    onSuccess: async (workspace) => {
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      await queryClient.invalidateQueries({ queryKey: ["org-workspaces", orgId] });
      onOpenChange(false);
      router.push(`/w/${workspace.slug}`);
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (orgId) create.mutate(String(new FormData(event.currentTarget).get("name")));
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-md">
          <form onSubmit={onSubmit} className="grid gap-4">
            <DialogHeader>
              <DialogTitle>Create a workspace</DialogTitle>
              <DialogDescription>
                Workspaces belong to an organisation, so you can invite people to them. You&apos;ll be its owner.
              </DialogDescription>
            </DialogHeader>
            <FormError message={create.isError ? errorMessage(create.error) : null} />
            {orgs.isLoading ? (
              <Skeleton className="h-24" />
            ) : manageable.length === 0 ? (
              <div className="grid gap-3 rounded-md border border-dashed p-4 text-sm">
                <p>
                  You don&apos;t own or run an organisation yet. Create one first; then its workspaces can have their own
                  members and projects.
                </p>
                <div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      onOpenChange(false); // one dialog at a time
                      setCreatingOrg(true);
                    }}
                  >
                    <Building2Icon />
                    Create an organisation
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <Field label="Name" name="name" placeholder="Acme engineering" required maxLength={100} autoFocus />
                <div className="grid gap-2">
                  <Label htmlFor="workspace-org">Organisation</Label>
                  <Select value={orgId ?? undefined} onValueChange={setPicked}>
                    <SelectTrigger id="workspace-org" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {manageable.map((o) => (
                        <SelectItem key={o.id} value={o.id}>
                          {o.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              {manageable.length > 0 && <SubmitButton pending={create.isPending}>Create workspace</SubmitButton>}
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <CreateOrgDialog open={creatingOrg} onOpenChange={setCreatingOrg} />
    </>
  );
}
