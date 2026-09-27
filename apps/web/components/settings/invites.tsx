"use client";

import type { Schemas } from "@pmagent/api-client";
import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Input } from "@pmagent/ui/components/input";
import { Label } from "@pmagent/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { CopyIcon, LinkIcon, MailIcon, XIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { SubmitButton } from "@/components/form";
import { timeAgo } from "@/components/issues/issue-activity";
import { useCreateInviteLink, useInviteByEmail, useInvites, useRevokeInvite } from "@/lib/admin";
import { ROLE_LABELS } from "@/lib/labels";

type EmailRole = Schemas["EmailInviteCreate"]["role"];
type LinkRole = Schemas["LinkInviteCreate"]["role"];

function inDays(iso: string): string {
  const days = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000));
  return days === 0 ? "today" : days === 1 ? "in 1 day" : `in ${days} days`;
}

function EmailInvite({ workspaceId, roles }: { workspaceId: string; roles: NonNullable<EmailRole>[] }) {
  const invite = useInviteByEmail(workspaceId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<EmailRole>(roles.includes("member") ? "member" : roles[0]);
  return (
    <form
      className="grid gap-2"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        invite.mutate({ email: email.trim(), role }, { onSuccess: () => setEmail("") });
      }}
    >
      <Label htmlFor="invite-email" className="flex items-center gap-1.5">
        <MailIcon className="size-4" /> Invite by email
      </Label>
      <div className="flex flex-wrap gap-2">
        <Input
          id="invite-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="teammate@company.com"
          required
          className="h-9 min-w-56 flex-1"
        />
        <Select value={role} onValueChange={(v) => setRole(v as EmailRole)}>
          <SelectTrigger className="h-9 w-28" aria-label="Role">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r} value={r}>
                {ROLE_LABELS[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <SubmitButton pending={invite.isPending} className="h-9">
          Send invite
        </SubmitButton>
      </div>
      <p className="text-muted-foreground text-xs">Valid for 7 days, for that address only. Inviting it again replaces the invite.</p>
    </form>
  );
}

function LinkInvite({ workspaceId, roles }: { workspaceId: string; roles: NonNullable<LinkRole>[] }) {
  const create = useCreateInviteLink(workspaceId);
  const [role, setRole] = useState<LinkRole>(roles.includes("member") ? "member" : roles[0]);
  const [maxUses, setMaxUses] = useState("");
  const [url, setUrl] = useState<string | null>(null);

  async function copy(text: string) {
    await navigator.clipboard.writeText(text);
    toast.success("Link copied");
  }

  return (
    <div className="grid gap-2">
      <Label className="flex items-center gap-1.5">
        <LinkIcon className="size-4" /> Invite link
      </Label>
      <div className="flex flex-wrap gap-2">
        <Select value={role} onValueChange={(v) => setRole(v as LinkRole)}>
          <SelectTrigger className="h-9 w-28" aria-label="Role for people who join">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {roles.map((r) => (
              <SelectItem key={r} value={r}>
                {ROLE_LABELS[r]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          type="number"
          min={1}
          max={1000}
          value={maxUses}
          onChange={(e) => setMaxUses(e.target.value)}
          placeholder="Any number of people"
          aria-label="Maximum uses"
          className="h-9 w-48"
        />
        <Button
          variant="outline"
          className="h-9"
          disabled={create.isPending}
          onClick={async () => {
            const link = await create
              .mutateAsync({ role, max_uses: maxUses ? Number(maxUses) : null, expires_in_days: 7 })
              .catch(() => null);
            if (link) {
              setUrl(link.url);
              await copy(link.url).catch(() => undefined);
            }
          }}
        >
          Create link
        </Button>
      </div>
      {url ? (
        <div className="bg-muted/50 flex items-center gap-2 rounded-md border p-2">
          <code className="min-w-0 flex-1 truncate font-mono text-xs">{url}</code>
          <Button size="sm" variant="ghost" onClick={() => void copy(url)}>
            <CopyIcon />
            Copy
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground text-xs">
          Anyone with the link joins as a member or guest for 7 days. The link is shown once; revoke it below if it leaks.
        </p>
      )}
    </div>
  );
}

/** Invite people (owners and admins), and the invites still waiting to be used. */
export function InvitesCard({ workspace }: { workspace: Schemas["WorkspaceWithRole"] }) {
  const invites = useInvites(workspace.id, true);
  const revoke = useRevokeInvite(workspace.id);
  // A personal workspace is yours alone: others can only look (guests).
  const personal = workspace.kind === "personal";
  return (
    <Card>
      <CardHeader>
        <CardTitle>Invite people</CardTitle>
        <CardDescription>
          {personal
            ? "A personal workspace is just for you; you can invite guests to look. Create a team workspace to work with others."
            : `They join ${workspace.name} with the role you choose.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <EmailInvite workspaceId={workspace.id} roles={personal ? ["guest"] : ["admin", "member", "guest"]} />
        <LinkInvite workspaceId={workspace.id} roles={personal ? ["guest"] : ["member", "guest"]} />
        <div className="grid gap-2">
          <h3 className="text-sm font-medium">Pending invites</h3>
          {invites.isLoading && <Skeleton className="h-16" />}
          {invites.data?.length === 0 && <p className="text-muted-foreground text-sm">None waiting.</p>}
          {invites.data && invites.data.length > 0 && (
            <ul className="divide-y rounded-md border">
              {invites.data.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
                  {i.kind === "email" ? (
                    <MailIcon className="text-muted-foreground size-4" />
                  ) : (
                    <LinkIcon className="text-muted-foreground size-4" />
                  )}
                  <div className="grid min-w-0 flex-1 gap-0.5">
                    <span className="truncate">{i.kind === "email" ? i.email : "Invite link"}</span>
                    <span className="text-muted-foreground text-xs">
                      Sent {timeAgo(i.created_at)} · expires {inDays(i.expires_at)}
                      {i.kind === "link" && ` · used ${i.use_count}${i.max_uses ? ` of ${i.max_uses}` : ""}`}
                    </span>
                  </div>
                  <Badge variant="outline">{ROLE_LABELS[i.role]}</Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={revoke.isPending && revoke.variables === i.id}
                    onClick={() => revoke.mutate(i.id)}
                  >
                    <XIcon />
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
