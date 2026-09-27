"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useState, type FormEvent } from "react";

import { Field, SubmitButton } from "@/components/form";
import { ORG_ROLE_HINTS, ORG_ROLE_LABELS, canManageOrg, useCurrentOrg, useRenameOrg, type Org } from "@/lib/orgs";

function Rename({ org }: { org: Org }) {
  const rename = useRenameOrg(org.id);
  const [name, setName] = useState(org.name);
  const canEdit = canManageOrg(org.role);
  return (
    <form
      className="grid gap-2"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        rename.mutate(name.trim());
      }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-56 flex-1">
          <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} disabled={!canEdit} />
        </div>
        {canEdit && (
          <SubmitButton pending={rename.isPending} disabled={rename.isPending || name.trim() === org.name}>
            Save
          </SubmitButton>
        )}
      </div>
      <p className="text-muted-foreground text-xs">Its address stays /o/{org.slug}.</p>
    </form>
  );
}

export default function OrgSettingsPage() {
  const { org } = useCurrentOrg();
  if (!org) return <Skeleton className="m-6 h-40 max-w-3xl" />;
  return (
    <div className="grid max-w-3xl content-start gap-4 p-4 md:p-6">
      <Card>
        <CardHeader>
          <CardTitle>General</CardTitle>
          <CardDescription>
            You&apos;re {org.role === "owner" ? "an" : "a"} {ORG_ROLE_LABELS[org.role].toLowerCase()}:{" "}
            {ORG_ROLE_HINTS[org.role].toLowerCase()}. Created {new Date(org.created_at).toLocaleDateString()}.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Rename key={org.name} org={org} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>What an organisation can see</CardTitle>
        </CardHeader>
        <CardContent className="text-muted-foreground grid gap-2 text-sm">
          <p>
            <span className="text-foreground font-medium">Owners</span> see and work in every workspace the organisation
            owns, as if they were an owner there.
          </p>
          <p>
            <span className="text-foreground font-medium">Admins</span> create workspaces, add people, and place them into
            workspaces, but only see inside the workspaces they&apos;ve been added to by an owner. Managing isn&apos;t
            reading.
          </p>
          <p>
            <span className="text-foreground font-medium">Members</span> see the organisation and the workspaces they&apos;re
            in.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
