"use client";

import type { Schemas } from "@pmagent/api-client";
import { Avatar, AvatarFallback } from "@pmagent/ui/components/avatar";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { CrownIcon, LogOutIcon, MoreHorizontalIcon, UserMinusIcon } from "lucide-react";
import { useRouter } from "next/navigation";

import { useConfirm } from "@/components/confirm-dialog";
import { timeAgo } from "@/components/issues/issue-activity";
import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { useChangeRole, useRemoveMember, useTransferOwnership, type Role } from "@/lib/admin";
import { useMembers } from "@/lib/issues";
import { ROLE_LABELS, canManageProjects, initials } from "@/lib/labels";
import { useMe } from "@/lib/queries";

const ROLE_HINTS: Record<Role, string> = {
  owner: "Everything, including billing and deleting the workspace",
  admin: "Settings, people, projects, and approvals",
  member: "Board, chat, approvals, and editing knowledge",
  guest: "Read only",
};

/** Everyone in the workspace. Owners and admins change roles and remove people; anyone can leave. */
export function MembersCard({ workspace }: { workspace: Schemas["WorkspaceWithRole"] }) {
  const router = useRouter();
  const me = useMe();
  const members = useMembers(workspace.id);
  const changeRole = useChangeRole(workspace.id);
  const remove = useRemoveMember(workspace.id);
  const transfer = useTransferOwnership(workspace.id);
  const [ask, confirmDialog] = useConfirm();
  const manage = canManageProjects(workspace.role);
  const iAmOwner = workspace.role === "owner";
  const personal = workspace.kind === "personal"; // only the owner and guests
  const assignable: Role[] = personal
    ? ["guest"]
    : iAmOwner
      ? ["owner", "admin", "member", "guest"]
      : ["admin", "member", "guest"];

  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>Members</SettingsTitle>
        <SettingsDescription>
          {members.data ? `${members.data.length} ${members.data.length === 1 ? "person" : "people"}` : "People"} in{" "}
          {workspace.name}.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent>
        {members.isLoading && <Skeleton className="h-32" />}
        <ul className="divide-y rounded-md border">
          {members.data?.map((m) => {
            const isMe = m.user_id === me.data?.id;
            const canChangeThisRole = manage && !isMe && !personal && (iAmOwner || m.role !== "owner");
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
                {canChangeThisRole ? (
                  <Select
                    value={m.role}
                    disabled={changeRole.isPending}
                    onValueChange={(role) => changeRole.mutate({ userId: m.user_id, role: role as Role })}
                  >
                    <SelectTrigger size="sm" className="w-28" aria-label={`Role for ${m.display_name}`}>
                      {/* Just the role name here; the options also carry a hint. */}
                      <SelectValue>{ROLE_LABELS[m.role]}</SelectValue>
                    </SelectTrigger>
                    <SelectContent align="end">
                      {assignable.map((r) => (
                        <SelectItem key={r} value={r}>
                          <span className="grid">
                            <span>{ROLE_LABELS[r]}</span>
                            <span className="text-muted-foreground text-xs">{ROLE_HINTS[r]}</span>
                          </span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Badge variant={m.role === "owner" ? "default" : "outline"}>{ROLE_LABELS[m.role]}</Badge>
                )}
                {(isMe || (manage && m.role !== "owner")) && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="icon" variant="ghost" className="size-8" aria-label={`More for ${m.display_name}`}>
                        <MoreHorizontalIcon />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {iAmOwner && !personal && !isMe && m.role !== "owner" && (
                        <DropdownMenuItem
                          onSelect={() =>
                            ask({
                              title: `Make ${m.display_name} the owner?`,
                              description: "They become the owner and you become an admin. Only they can undo this.",
                              confirm: "Transfer ownership",
                              action: () => transfer.mutateAsync(m.user_id),
                            })
                          }
                        >
                          <CrownIcon />
                          Make owner
                        </DropdownMenuItem>
                      )}
                      {manage && !isMe && m.role !== "owner" && (
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onSelect={() =>
                            ask({
                              title: `Remove ${m.display_name}?`,
                              description: "They lose access to this workspace and its projects. You can invite them again.",
                              confirm: "Remove",
                              destructive: true,
                              action: () => remove.mutateAsync(m.user_id),
                            })
                          }
                        >
                          <UserMinusIcon />
                          Remove from workspace
                        </DropdownMenuItem>
                      )}
                      {isMe && (
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onSelect={() =>
                            ask({
                              title: `Leave ${workspace.name}?`,
                              description:
                                m.role === "owner"
                                  ? "Owners can't leave while they're the only owner: make someone else the owner first."
                                  : "You lose access to its projects until someone invites you again.",
                              confirm: "Leave workspace",
                              destructive: true,
                              action: async () => {
                                await remove.mutateAsync(m.user_id);
                                router.push("/");
                              },
                            })
                          }
                        >
                          <LogOutIcon />
                          Leave workspace
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </li>
            );
          })}
        </ul>
        {confirmDialog}
      </SettingsContent>
    </SettingsSection>
  );
}
