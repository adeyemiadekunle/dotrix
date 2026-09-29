"use client";

import { Avatar, AvatarFallback } from "@pmagent/ui/components/avatar";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Input } from "@pmagent/ui/components/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { LogOutIcon, UserMinusIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useConfirm } from "@/components/confirm-dialog";
import { SubmitButton } from "@/components/form";
import { timeAgo } from "@/components/issues/issue-activity";
import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { initials } from "@/lib/labels";
import {
  ORG_ROLE_HINTS,
  ORG_ROLE_LABELS,
  canManageOrg,
  useAddOrgMember,
  useChangeOrgRole,
  useCurrentOrg,
  useOrgMembers,
  useRemoveOrgMember,
  type Org,
  type OrgRole,
} from "@/lib/orgs";
import { useMe } from "@/lib/queries";

function AddMember({ org }: { org: Org }) {
  const add = useAddOrgMember(org.id);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>("member");
  const roles: OrgRole[] = org.role === "owner" ? ["owner", "admin", "member"] : ["admin", "member"];
  return (
    <form
      className="grid gap-2"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        add.mutate({ email: email.trim(), role }, { onSuccess: () => setEmail("") });
      }}
    >
      <div className="flex flex-wrap gap-2">
        <Input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="teammate@company.com"
          required
          className="h-9 min-w-56 flex-1"
          aria-label="Email of the person to add"
        />
        <Select value={role} onValueChange={(v) => setRole(v as OrgRole)}>
          <SelectTrigger className="h-9 w-28" aria-label="Organisation role">
            <SelectValue>{ORG_ROLE_LABELS[role]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r} value={r}>
                <span className="grid">
                  <span>{ORG_ROLE_LABELS[r]}</span>
                  <span className="text-muted-foreground text-xs">{ORG_ROLE_HINTS[r]}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <SubmitButton pending={add.isPending} className="h-9">
          Add
        </SubmitButton>
      </div>
      <p className="text-muted-foreground text-xs">
        They need a pmagent account already. Joining the organisation doesn&apos;t put them in any workspace; place them from
        the Workspaces tab.
      </p>
    </form>
  );
}

/** The organisation's people. Owners and admins add, change, and remove; anyone can leave. */
export default function OrgMembersPage() {
  const router = useRouter();
  const { org } = useCurrentOrg();
  const me = useMe();
  const members = useOrgMembers(org?.id);
  const changeRole = useChangeOrgRole(org?.id ?? "");
  const remove = useRemoveOrgMember(org?.id ?? "");
  const [ask, confirmDialog] = useConfirm();
  if (!org) return <Skeleton className="m-6 h-64 max-w-3xl" />;
  const manage = canManageOrg(org.role);

  return (
    <div className="grid max-w-5xl content-start gap-8 p-4 md:p-8">
      {manage && (
        <SettingsSection>
          <SettingsHeader>
            <SettingsTitle>Add someone</SettingsTitle>
            <SettingsDescription>Everyone in the organisation&apos;s workspaces is an organisation member.</SettingsDescription>
          </SettingsHeader>
          <SettingsContent>
            <AddMember org={org} />
          </SettingsContent>
        </SettingsSection>
      )}
      <SettingsSection>
        <SettingsHeader>
          <SettingsTitle>Members</SettingsTitle>
          <SettingsDescription>
            {members.data ? `${members.data.length} ${members.data.length === 1 ? "person" : "people"}` : "People"}. Removing
            someone also removes them from the organisation&apos;s workspaces.
          </SettingsDescription>
        </SettingsHeader>
        <SettingsContent>
          {members.isLoading && <Skeleton className="h-32" />}
          <ul className="divide-y rounded-md border">
            {members.data?.map((m) => {
              const isMe = m.user_id === me.data?.id;
              const canChange = manage && !isMe && (org.role === "owner" || m.role !== "owner");
              const roles: OrgRole[] = org.role === "owner" ? ["owner", "admin", "member"] : ["admin", "member"];
              return (
                <li key={m.user_id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                  <Avatar className="size-8">
                    <AvatarFallback className="text-xs">{initials(m.display_name)}</AvatarFallback>
                  </Avatar>
                  <div className="grid min-w-0 flex-1 gap-0.5">
                    <span className="flex items-center gap-2 truncate font-medium">
                      {m.display_name}
                      {isMe && <Badge variant="secondary">You</Badge>}
                    </span>
                    <span className="text-muted-foreground truncate text-xs">
                      {m.email} · joined {timeAgo(m.joined_at)}
                    </span>
                  </div>
                  {canChange ? (
                    <Select
                      value={m.role}
                      disabled={changeRole.isPending}
                      onValueChange={(role) => changeRole.mutate({ userId: m.user_id, role: role as OrgRole })}
                    >
                      <SelectTrigger size="sm" className="w-28" aria-label={`Organisation role for ${m.display_name}`}>
                        <SelectValue>{ORG_ROLE_LABELS[m.role]}</SelectValue>
                      </SelectTrigger>
                      <SelectContent align="end">
                        {roles.map((r) => (
                          <SelectItem key={r} value={r}>
                            <span className="grid">
                              <span>{ORG_ROLE_LABELS[r]}</span>
                              <span className="text-muted-foreground text-xs">{ORG_ROLE_HINTS[r]}</span>
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Badge variant={m.role === "owner" ? "default" : "outline"}>{ORG_ROLE_LABELS[m.role]}</Badge>
                  )}
                  {(isMe || (manage && m.role !== "owner")) && (
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8"
                      aria-label={isMe ? "Leave the organisation" : `Remove ${m.display_name}`}
                      onClick={() =>
                        ask(
                          isMe
                            ? {
                                title: `Leave ${org.name}?`,
                                description:
                                  "You also leave its workspaces. If you own one of them, hand it over first. The organisation always keeps an owner.",
                                confirm: "Leave organisation",
                                destructive: true,
                                action: async () => {
                                  await remove.mutateAsync(m.user_id);
                                  router.push("/");
                                },
                              }
                            : {
                                title: `Remove ${m.display_name}?`,
                                description:
                                  "They're also removed from every workspace in the organisation. Anyone who owns one of its workspaces must hand it over first.",
                                confirm: "Remove",
                                destructive: true,
                                action: () => remove.mutateAsync(m.user_id),
                              },
                        )
                      }
                    >
                      {isMe ? <LogOutIcon /> : <UserMinusIcon />}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
          {confirmDialog}
        </SettingsContent>
      </SettingsSection>
    </div>
  );
}
