import type { Schemas } from "@pmagent/api-client";
import { Checkbox } from "@pmagent/ui/components/checkbox";
import { Label } from "@pmagent/ui/components/label";
import { useState, type FormEvent } from "react";

import { Field, SaveBar } from "@/components/form";
import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { useMemberPermissions, useRenameWorkspace } from "@/lib/admin";
import {
  MEMBER_GRANTS,
  ROLE_LABELS,
  WORKSPACE_KIND_LABELS,
  canManageProjects,
  withArticle,
  type Permission,
} from "@/lib/labels";

// The workspace's own settings: its name, and what members may do.

export function GeneralCard({ workspace }: { workspace: Schemas["WorkspaceWithRole"] }) {
  const rename = useRenameWorkspace(workspace.id);
  const [name, setName] = useState(workspace.name);
  const canEdit = canManageProjects(workspace.role);
  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>General</SettingsTitle>
        <SettingsDescription>
          {WORKSPACE_KIND_LABELS[workspace.kind]} · you&apos;re {withArticle(ROLE_LABELS[workspace.role].toLowerCase())}.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent>
        <form
          className="grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            rename.mutate(name.trim());
          }}
        >
          <Field
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={100}
            disabled={!canEdit}
          />
          <p className="text-muted-foreground text-xs">Its address stays /w/{workspace.slug}.</p>
          {canEdit && (
            <SaveBar dirty={name.trim() !== workspace.name} pending={rename.isPending} onDiscard={() => setName(workspace.name)} />
          )}
        </form>
      </SettingsContent>
    </SettingsSection>
  );
}

/** What members may do beyond chatting, brainstorming, and working the board. Owners and admins
 * change it; everyone can see it. */
export function MemberPermissionsCard({ workspace }: { workspace: Schemas["WorkspaceWithRole"] }) {
  const save = useMemberPermissions(workspace.id);
  const canEdit = canManageProjects(workspace.role);
  const granted = new Set(workspace.member_permissions ?? []);

  function toggle(permission: Permission, on: boolean) {
    const next = MEMBER_GRANTS.map((g) => g.permission).filter((p) => (p === permission ? on : granted.has(p)));
    save.mutate(next);
  }

  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>What members can do</SettingsTitle>
        <SettingsDescription>
          Members always chat, brainstorm, and work the board. Changes to the project&apos;s documents are for owners and
          admins: a change a member asks the agents for waits for one of you to review it. You can let members do more.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="grid gap-3">
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
      </SettingsContent>
    </SettingsSection>
  );
}
