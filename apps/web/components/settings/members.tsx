import type { Schemas } from "@dotrix/api-client";
import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@dotrix/ui/components/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@dotrix/ui/components/select";
import { Input } from "@dotrix/ui/components/input";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { cn } from "@dotrix/ui/lib/utils";
import { CrownIcon, LogOutIcon, MoreHorizontalIcon, SearchIcon, UserMinusIcon } from "lucide-react";
import { useRouter } from "@/lib/navigation";
import { useMemo, useState } from "react";

import { useConfirm } from "@/components/confirm-dialog";
import { timeAgo } from "@/components/issues/issue-activity";
import { SettingsContent, SettingsDescription, SettingsHeader, SettingsSection, SettingsTitle } from "@/components/settings-section";
import { UserAvatar } from "@/components/user-avatar";
import { useChangeRole, useRemoveMember, useTransferOwnership, type Member, type Role } from "@/lib/admin";
import { useMembers } from "@/lib/issues";
import { ROLE_LABELS, canManageProjects } from "@/lib/labels";
import { memberAvatarSrc } from "@/lib/profile";
import { useMe, useProjects } from "@/lib/queries";

const ROLE_HINTS: Record<Role, string> = {
  owner: "Everything, including billing and deleting the workspace",
  admin: "Settings, people, projects, and approvals",
  member: "Board, chat, approvals, and editing knowledge",
  guest: "Read only",
};

const ROLE_ORDER: Role[] = ["owner", "admin", "member", "guest"];
const ROLE_PLURALS: Record<Role, string> = { owner: "Owners", admin: "Admins", member: "Members", guest: "Guests" };

/** "All projects", "None", or the first names and how many more (all of them on hover). */
function ProjectsTheySee({ member, names }: { member: Member; names: Map<string, string> }) {
  if (member.sees_all_projects) return <span>All projects</span>;
  const seen = member.project_ids.map((id) => names.get(id)).filter((n): n is string => Boolean(n));
  if (seen.length === 0) return <span>{member.role === "guest" ? "None (guests see no projects)" : "None"}</span>;
  const shown = seen.slice(0, 2).join(", ");
  return <span title={seen.join(", ")}>{seen.length > 2 ? `${shown} +${seen.length - 2}` : shown}</span>;
}

/** Everyone in the workspace. Owners and admins change roles and remove people; anyone can leave. */
export function MembersCard({ workspace }: { workspace: Schemas["WorkspaceWithRole"] }) {
  const router = useRouter();
  const me = useMe();
  const members = useMembers(workspace.id);
  const projects = useProjects(workspace.id);
  const projectNames = useMemo(() => new Map(projects.data?.map((p) => [p.id, p.name])), [projects.data]);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<Role | null>(null);
  const counts = useMemo(() => {
    const out = new Map<Role, number>();
    for (const m of members.data ?? []) out.set(m.role, (out.get(m.role) ?? 0) + 1);
    return out;
  }, [members.data]);
  const q = query.trim().toLowerCase();
  const shown = (members.data ?? []).filter(
    (m) => (!roleFilter || m.role === roleFilter) && (!q || [m.display_name, m.email, m.title ?? ""].some((text) => text.toLowerCase().includes(q))),
  );
  const changeRole = useChangeRole(workspace.id);
  const remove = useRemoveMember(workspace.id);
  const transfer = useTransferOwnership(workspace.id);
  const [ask, confirmDialog] = useConfirm();
  const manage = canManageProjects(workspace.role);
  const iAmOwner = workspace.role === "owner";
  const personal = workspace.kind === "personal"; // only the owner and guests
  const assignable: Role[] = personal ? ["guest"] : iAmOwner ? ["owner", "admin", "member", "guest"] : ["admin", "member", "guest"];

  return (
    <SettingsSection stacked>
      <SettingsHeader>
        <SettingsTitle>Members</SettingsTitle>
        <SettingsDescription>
          {members.data ? `${members.data.length} ${members.data.length === 1 ? "person" : "people"}` : "People"} in {workspace.name}.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name, email, or what they do"
              aria-label="Search members"
              className="h-8 pl-8"
            />
          </div>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by role">
            {[null, ...ROLE_ORDER.filter((r) => counts.has(r))].map((r) => (
              <button
                key={r ?? "all"}
                type="button"
                aria-pressed={roleFilter === r}
                onClick={() => setRoleFilter(r)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                  roleFilter === r ? "bg-primary text-primary-foreground border-primary" : "hover:bg-muted",
                )}
              >
                {r ? ROLE_PLURALS[r] : "All"} <span className="tabular-nums opacity-70">{r ? counts.get(r) : (members.data?.length ?? 0)}</span>
              </button>
            ))}
          </div>
        </div>
        {members.isLoading && <Skeleton className="h-32" />}
        {members.data && shown.length === 0 && <p className="text-muted-foreground py-4 text-center text-sm">Nobody matches.</p>}
        <ul className="divide-y rounded-md border empty:hidden">
          {shown.map((m) => {
            const isMe = m.user_id === me.data?.id;
            const canChangeThisRole = manage && !isMe && !personal && (iAmOwner || m.role !== "owner");
            return (
              <li key={m.user_id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                <UserAvatar name={m.display_name} src={memberAvatarSrc(workspace.id, m)} />
                <div className="grid min-w-0 flex-1 basis-48 gap-0.5">
                  <span className="flex items-center gap-2 truncate font-medium">
                    {m.display_name}
                    {isMe && <Badge variant="secondary">You</Badge>}
                    {m.title && <span className="text-muted-foreground truncate text-xs font-normal">{m.title}</span>}
                  </span>
                  <span className="text-muted-foreground truncate text-xs">
                    {m.email} · joined {timeAgo(m.joined_at)}
                  </span>
                </div>
                <div className="grid w-40 gap-0.5 text-xs">
                  <span className="text-muted-foreground">Projects they see</span>
                  <span className="truncate" data-testid="projects-they-see">
                    <ProjectsTheySee member={m} names={projectNames} />
                  </span>
                </div>
                {/* The role and the menu take the same room in every row, so the columns line up. */}
                <div className="flex w-28 shrink-0 justify-end">
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
                </div>
                {isMe || (manage && m.role !== "owner") ? (
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
                ) : (
                  <span className="size-8 shrink-0" aria-hidden />
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
