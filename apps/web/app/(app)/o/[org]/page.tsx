"use client";

import { Badge } from "@pmagent/ui/components/badge";
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
import {
  ChevronDownIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
  FolderInputIcon,
  LayoutGridIcon,
  LockIcon,
  PlusIcon,
  UnlinkIcon,
  UserMinusIcon,
} from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { useConfirm } from "@/components/confirm-dialog";
import { Field, SubmitButton } from "@/components/form";
import { EmptyState } from "@/components/states";
import { ROLE_LABELS, WORKSPACE_KIND_LABELS, initials } from "@/lib/labels";
import {
  canManageOrg,
  useAttachWorkspace,
  useCreateOrgWorkspace,
  useCurrentOrg,
  useDetachWorkspace,
  useOrgMembers,
  useOrgWorkspaceMembers,
  useOrgWorkspaces,
  usePlace,
  useUnplace,
  type Org,
  type OrgWorkspace,
  type PlaceableRole,
} from "@/lib/orgs";
import { useMe, useWorkspaces } from "@/lib/queries";

const PLACEABLE: NonNullable<PlaceableRole>[] = ["admin", "member", "guest"];

function NewWorkspaceDialog({ org, open, onOpenChange }: { org: Org; open: boolean; onOpenChange: (o: boolean) => void }) {
  const create = useCreateOrgWorkspace(org.id);
  const members = useOrgMembers(org.id);
  const me = useMe();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"team" | "business">("business");
  const [owner, setOwner] = useState<string>("me");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-md">
        <form
          className="grid gap-4"
          onSubmit={async (e: FormEvent) => {
            e.preventDefault();
            const done = await create
              .mutateAsync({ name: name.trim(), kind, owner_user_id: owner === "me" ? null : owner })
              .catch(() => null);
            if (done) {
              onOpenChange(false);
              setName("");
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>New workspace in {org.name}</DialogTitle>
            <DialogDescription>Its owner runs it; the organisation manages who&apos;s in it.</DialogDescription>
          </DialogHeader>
          <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Payments team" required maxLength={100} autoFocus />
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label>Kind</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as typeof kind)}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="business">Business</SelectItem>
                  <SelectItem value="team">Team</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>Owner</Label>
              <Select value={owner} onValueChange={setOwner}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="me">You</SelectItem>
                  {members.data
                    ?.filter((m) => m.user_id !== me.data?.id)
                    .map((m) => (
                      <SelectItem key={m.user_id} value={m.user_id}>
                        {m.display_name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={create.isPending}>Create workspace</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AttachDialog({ org, open, onOpenChange }: { org: Org; open: boolean; onOpenChange: (o: boolean) => void }) {
  const attach = useAttachWorkspace(org.id);
  const workspaces = useWorkspaces();
  // Only team or business workspaces you own that aren't in an organisation yet.
  const candidates = (workspaces.data ?? []).filter(
    (w) => w.role === "owner" && !w.via_organization && w.kind !== "personal" && !w.organization_id,
  );
  const [choice, setChoice] = useState<string>("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-md">
        <form
          className="grid gap-4"
          onSubmit={async (e: FormEvent) => {
            e.preventDefault();
            if (!choice) return;
            const done = await attach.mutateAsync(choice).catch(() => null);
            if (done) {
              onOpenChange(false);
              setChoice("");
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>Add a workspace to {org.name}</DialogTitle>
            <DialogDescription>
              A team or business workspace you own. Its people join the organisation as members; the workspace keeps its
              projects and roles.
            </DialogDescription>
          </DialogHeader>
          {candidates.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              You don&apos;t own a team or business workspace outside an organisation. Personal workspaces can&apos;t be
              added.
            </p>
          ) : (
            <Select value={choice} onValueChange={setChoice}>
              <SelectTrigger className="w-full" aria-label="Workspace">
                <SelectValue placeholder="Choose a workspace" />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((w) => (
                  <SelectItem key={w.id} value={w.id}>
                    {w.name} · {WORKSPACE_KIND_LABELS[w.kind]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={attach.isPending} disabled={!choice || attach.isPending}>
              Add workspace
            </SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Who's in one of the organisation's workspaces, and placing org members into it. */
function WorkspacePeople({ org, workspace }: { org: Org; workspace: OrgWorkspace }) {
  const people = useOrgWorkspaceMembers(org.id, workspace.id, true);
  const orgMembers = useOrgMembers(org.id);
  const me = useMe();
  const place = usePlace(org.id);
  const unplace = useUnplace(org.id);
  const [adding, setAdding] = useState<string>("");
  const [role, setRole] = useState<NonNullable<PlaceableRole>>("member");
  const inIt = new Set(people.data?.map((p) => p.user_id));
  // Org admins can't place themselves: seeing inside a workspace needs its owner's say.
  const addable = (orgMembers.data ?? []).filter(
    (m) => !inIt.has(m.user_id) && (org.role === "owner" || m.user_id !== me.data?.id),
  );

  return (
    <div className="grid gap-3 border-t pt-3">
      {people.isLoading && <Skeleton className="h-16" />}
      <ul className="grid gap-1">
        {people.data?.map((p) => (
          <li key={p.user_id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate">
              {p.display_name} <span className="text-muted-foreground text-xs">{p.email}</span>
            </span>
            {p.role === "owner" ? (
              <Badge>Owner</Badge>
            ) : (
              <Select
                value={p.role}
                onValueChange={(r) => place.mutate({ workspaceId: workspace.id, userId: p.user_id, role: r as PlaceableRole })}
              >
                <SelectTrigger size="sm" className="h-8 w-28" aria-label={`Role of ${p.display_name} in ${workspace.name}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  {PLACEABLE.map((r) => (
                    <SelectItem key={r} value={r}>
                      {ROLE_LABELS[r]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {p.role !== "owner" && (
              <Button
                size="icon"
                variant="ghost"
                className="size-8"
                aria-label={`Take ${p.display_name} out of ${workspace.name}`}
                disabled={unplace.isPending}
                onClick={() => unplace.mutate({ workspaceId: workspace.id, userId: p.user_id })}
              >
                <UserMinusIcon />
              </Button>
            )}
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (!adding) return;
          place.mutate({ workspaceId: workspace.id, userId: adding, role }, { onSuccess: () => setAdding("") });
        }}
      >
        <Select value={adding} onValueChange={setAdding} disabled={addable.length === 0}>
          <SelectTrigger size="sm" className="h-8 min-w-48 flex-1" aria-label="Organisation member to add">
            <SelectValue placeholder={addable.length ? "Add an organisation member" : "Everyone's already in it"} />
          </SelectTrigger>
          <SelectContent>
            {addable.map((m) => (
              <SelectItem key={m.user_id} value={m.user_id}>
                {m.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={role} onValueChange={(v) => setRole(v as NonNullable<PlaceableRole>)}>
          <SelectTrigger size="sm" className="h-8 w-28" aria-label="Role in the workspace">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PLACEABLE.map((r) => (
              <SelectItem key={r} value={r}>
                {ROLE_LABELS[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <SubmitButton pending={place.isPending} size="sm" className="h-8" disabled={!adding || place.isPending}>
          <PlusIcon />
          Add
        </SubmitButton>
      </form>
    </div>
  );
}

function WorkspaceRow({ org, workspace }: { org: Org; workspace: OrgWorkspace }) {
  const manage = canManageOrg(org.role);
  const [open, setOpen] = useState(false);
  const detach = useDetachWorkspace(org.id);
  const [ask, confirmDialog] = useConfirm();
  return (
    <li className="grid gap-3 px-4 py-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {manage && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label={`People in ${workspace.name}`}
            className="text-muted-foreground hover:text-foreground -ml-1 flex size-7 items-center justify-center rounded-md"
          >
            {open ? <ChevronDownIcon className="size-4" /> : <ChevronRightIcon className="size-4" />}
          </button>
        )}
        <span className="bg-brand-muted text-brand-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-lg text-xs font-semibold">
          {initials(workspace.name)}
        </span>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="flex flex-wrap items-center gap-2 font-medium">
            {workspace.name}
            <Badge variant="outline">{WORKSPACE_KIND_LABELS[workspace.kind]}</Badge>
          </span>
          <span className="text-muted-foreground text-xs">
            {workspace.members} {workspace.members === 1 ? "person" : "people"} · {workspace.projects}{" "}
            {workspace.projects === 1 ? "project" : "projects"}
            {workspace.your_role
              ? ` · you're ${ROLE_LABELS[workspace.your_role].toLowerCase()}${workspace.via_organization ? " through the organisation" : ""}`
              : " · you're not in it"}
          </span>
        </div>
        {workspace.your_role ? (
          <Button size="sm" variant="outline" asChild>
            <Link href={`/w/${workspace.slug}`}>
              Open
              <ExternalLinkIcon />
            </Link>
          </Button>
        ) : (
          <span className="text-muted-foreground flex items-center gap-1 text-xs" title="Seeing inside needs a place in it">
            <LockIcon className="size-3.5" /> Not in it
          </span>
        )}
        {manage && (
          <Button
            size="icon"
            variant="ghost"
            className="size-8"
            aria-label={`Take ${workspace.name} out of the organisation`}
            onClick={() =>
              ask({
                title: `Take ${workspace.name} out of ${org.name}?`,
                description:
                  "It becomes a standalone workspace with the same people, projects, and roles. Its people stay organisation members.",
                confirm: "Take it out",
                action: () => detach.mutateAsync(workspace.id),
              })
            }
          >
            <UnlinkIcon />
          </Button>
        )}
      </div>
      {manage && open && <WorkspacePeople org={org} workspace={workspace} />}
      {confirmDialog}
    </li>
  );
}

/** The organisation's workspaces: names and sizes for everyone; content only for those in them. */
export default function OrgWorkspacesPage() {
  const { org } = useCurrentOrg();
  const workspaces = useOrgWorkspaces(org?.id);
  const [creating, setCreating] = useState(false);
  const [attaching, setAttaching] = useState(false);
  if (!org) return <Skeleton className="m-6 h-64 max-w-3xl" />;
  const manage = canManageOrg(org.role);

  return (
    <div className="grid max-w-5xl content-start gap-6 p-4 md:p-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-1">
          <h2 className="text-lg font-semibold">Workspaces</h2>
          <p className="text-muted-foreground text-sm">
            {org.role === "owner"
              ? "As an owner you see inside every workspace the organisation owns."
              : org.role === "admin"
                ? "You manage every workspace's people, but see inside only the ones you're in."
                : "The workspaces you're in."}
          </p>
        </div>
        {manage && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setAttaching(true)}>
              <FolderInputIcon />
              Add an existing workspace
            </Button>
            <Button size="sm" onClick={() => setCreating(true)}>
              <PlusIcon />
              New workspace
            </Button>
          </div>
        )}
      </div>
      {workspaces.isLoading && <Skeleton className="h-32" />}
      {workspaces.data?.length === 0 && (
        <EmptyState
          icon={LayoutGridIcon}
          title="No workspaces yet"
          description={
            manage
              ? "Create one for each team or product, or add a workspace you already own."
              : "When someone places you in one of the organisation's workspaces, it appears here."
          }
        />
      )}
      {workspaces.data && workspaces.data.length > 0 && (
        <ul className="bg-card divide-y rounded-xl border shadow-xs">
          {workspaces.data.map((w) => (
            <WorkspaceRow key={w.id} org={org} workspace={w} />
          ))}
        </ul>
      )}
      {manage && <NewWorkspaceDialog org={org} open={creating} onOpenChange={setCreating} />}
      {manage && <AttachDialog org={org} open={attaching} onOpenChange={setAttaching} />}
    </div>
  );
}
