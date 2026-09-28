"use client";

import type { Schemas } from "@pmagent/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Checkbox } from "@pmagent/ui/components/checkbox";
import { Label } from "@pmagent/ui/components/label";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app-shell";
import { Field, SubmitButton } from "@/components/form";
import { InvitesCard } from "@/components/settings/invites";
import { MembersCard } from "@/components/settings/members";
import { NotFound } from "@/components/states";
import { useMemberPermissions, useRenameWorkspace } from "@/lib/admin";
import {
  MEMBER_GRANTS,
  ROLE_LABELS,
  WORKSPACE_KIND_LABELS,
  canManageProjects,
  withArticle,
  type Permission,
} from "@/lib/labels";
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

/** What members may do beyond chatting, brainstorming, and working the board. Owners and admins
 * change it; everyone can see it. */
function MemberPermissionsCard({ workspace }: { workspace: Schemas["WorkspaceWithRole"] }) {
  const save = useMemberPermissions(workspace.id);
  const canEdit = canManageProjects(workspace.role);
  const granted = new Set(workspace.member_permissions ?? []);

  function toggle(permission: Permission, on: boolean) {
    const next = MEMBER_GRANTS.map((g) => g.permission).filter((p) => (p === permission ? on : granted.has(p)));
    save.mutate(next);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>What members can do</CardTitle>
        <CardDescription>
          Members always chat, brainstorm, and work the board. Changes to the project&apos;s documents are for owners and
          admins: a change a member asks the agents for waits for one of you to review it. You can let members do more.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {MEMBER_GRANTS.map((grant) => (
          <Label key={grant.permission} className="flex items-start gap-3 font-normal">
            <Checkbox
              className="mt-0.5"
              checked={granted.has(grant.permission)}
              disabled={!canEdit || save.isPending}
              onCheckedChange={(checked) => toggle(grant.permission, checked === true)}
              aria-label={grant.label}
            />
            <span className="grid gap-0.5">
              <span className="font-medium">{grant.label}</span>
              <span className="text-muted-foreground text-xs">{grant.description}</span>
            </span>
          </Label>
        ))}
        {!canEdit && <p className="text-muted-foreground text-xs">Only owners and admins change these.</p>}
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
            {workspace.kind !== "personal" && <MemberPermissionsCard workspace={workspace} />}
            <MembersCard workspace={workspace} />
            {canManageProjects(workspace.role) && !workspace.via_organization && <InvitesCard workspace={workspace} />}
          </>
        )}
      </div>
    </>
  );
}
