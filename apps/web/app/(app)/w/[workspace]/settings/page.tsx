"use client";

import type { Schemas } from "@pmagent/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app-shell";
import { Field, SubmitButton } from "@/components/form";
import { InvitesCard } from "@/components/settings/invites";
import { MembersCard } from "@/components/settings/members";
import { NotFound } from "@/components/states";
import { useRenameWorkspace } from "@/lib/admin";
import { ROLE_LABELS, WORKSPACE_KIND_LABELS, canManageProjects, withArticle } from "@/lib/labels";
import { useCurrentWorkspace } from "@/lib/queries";

function GeneralCard({ workspace }: { workspace: Schemas["WorkspaceWithRole"] }) {
  const rename = useRenameWorkspace(workspace.id);
  const [name, setName] = useState(workspace.name);
  const canEdit = canManageProjects(workspace.role);
  return (
    <Card>
      <CardHeader>
        <CardTitle>General</CardTitle>
        <CardDescription>
          {WORKSPACE_KIND_LABELS[workspace.kind]} workspace · you&apos;re {withArticle(ROLE_LABELS[workspace.role].toLowerCase())}
          {workspace.via_organization && " through its organisation"}.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            rename.mutate(name.trim());
          }}
        >
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-56 flex-1">
              <Field
                label="Name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={100}
                disabled={!canEdit}
              />
            </div>
            {canEdit && (
              <SubmitButton pending={rename.isPending} disabled={rename.isPending || name.trim() === workspace.name}>
                Save
              </SubmitButton>
            )}
          </div>
          <p className="text-muted-foreground text-xs">Its address stays /w/{workspace.slug}.</p>
        </form>
      </CardContent>
    </Card>
  );
}

/** The workspace's settings, people, and invites. Everyone sees the people; admins manage them. */
export default function WorkspaceSettingsPage() {
  const { workspace, notFound } = useCurrentWorkspace();
  if (notFound) return <NotFound what="workspace" />;
  return (
    <>
      <PageHeader title="Settings" parent={workspace?.name} />
      <div className="grid max-w-3xl content-start gap-4 p-4 md:p-6">
        {!workspace ? (
          <Skeleton className="h-64" />
        ) : (
          <>
            <GeneralCard key={workspace.id} workspace={workspace} />
            <MembersCard workspace={workspace} />
            {canManageProjects(workspace.role) && !workspace.via_organization && <InvitesCard workspace={workspace} />}
          </>
        )}
      </div>
    </>
  );
}
