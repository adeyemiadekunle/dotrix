"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@pmagent/ui/components/dialog";
import { Input } from "@pmagent/ui/components/input";
import { Label } from "@pmagent/ui/components/label";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { BoxIcon, FileTextIcon, LinkIcon, PlusIcon, SparklesIcon, TicketIcon, TriangleAlertIcon, XIcon } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import type { Scope } from "@/lib/issues";
import {
  LINK_LABELS,
  LINKABLE,
  useAddLink,
  useNeighbors,
  useRemoveLink,
  useStale,
  type EdgeKind,
  type GraphLink,
  type GraphNode,
} from "@/lib/graph";

const ICONS = { document: FileTextIcon, issue: TicketIcon, module: BoxIcon } as const;

/** Where a node opens: a document in Knowledge, an issue in its drawer on the board. */
export function nodeHref(projectBase: string, node: Pick<GraphNode, "kind" | "ref">): string | null {
  if (node.kind === "document") return `${projectBase}/knowledge?file=${encodeURIComponent(node.ref)}`;
  if (node.kind === "issue") return `${projectBase}/board?issue=${encodeURIComponent(node.ref)}`;
  return null;
}

/** "May be out of date" for one document, from the graph. */
export function StaleNotice({ scope, path }: { scope: Scope; path: string }) {
  const stale = useStale(scope);
  const found = stale.data?.find((s) => s.node.ref === path);
  if (!found) return null;
  return (
    <div className="bg-warning-muted flex gap-2 rounded-lg p-3 text-sm" role="note">
      <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" />
      <div className="grid gap-0.5">
        <p className="font-medium">This may be out of date</p>
        <ul className="text-muted-foreground list-disc pl-4 text-xs">
          {found.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** What something links to and what links to it, grouped by how; add or remove links by hand. */
export function Related({
  scope,
  refName,
  projectBase,
  canEdit,
  compact = false,
}: {
  scope: Scope;
  refName: string;
  projectBase: string;
  canEdit: boolean;
  compact?: boolean;
}) {
  const neighbors = useNeighbors(scope, refName);
  const remove = useRemoveLink(scope);
  const [adding, setAdding] = useState(false);

  const groups = new Map<string, GraphLink[]>();
  for (const link of neighbors.data?.links ?? []) {
    const label = LINK_LABELS[link.kind][link.direction];
    groups.set(label, [...(groups.get(label) ?? []), link]);
  }

  return (
    <section className="grid gap-2" aria-label="Related">
      <div className="flex items-center gap-2">
        <h3 className={compact ? "text-muted-foreground text-xs font-medium" : "text-sm font-medium"}>Related</h3>
        {canEdit && neighbors.data && (
          <Button size="sm" variant="ghost" className="ml-auto h-7" onClick={() => setAdding(true)}>
            <PlusIcon />
            Link
          </Button>
        )}
      </div>
      {neighbors.isLoading ? (
        <Skeleton className="h-12" />
      ) : neighbors.isError || !neighbors.data ? (
        <p className="text-muted-foreground text-xs">Not linked to anything yet.</p>
      ) : groups.size === 0 ? (
        <p className="text-muted-foreground text-xs">
          Not linked to anything yet. Links come from issue keys and document paths in the text, epics and
          dependencies, and decisions&apos; &quot;Affected modules&quot; and &quot;Supersedes&quot;.
        </p>
      ) : (
        <dl className="grid gap-2">
          {[...groups].map(([label, links]) => (
            <div key={label} className="grid gap-1">
              <dt className="text-muted-foreground text-xs">{label}</dt>
              {links.map((link) => {
                const Icon = ICONS[link.node.kind];
                const href = nodeHref(projectBase, link.node);
                const name = link.node.kind === "module" ? link.node.title : link.node.ref;
                return (
                  <dd key={link.id} className="group flex min-w-0 items-center gap-2 text-sm">
                    <Icon className="text-muted-foreground size-3.5 shrink-0" />
                    {href ? (
                      <Link href={href} className="truncate font-mono text-xs hover:underline" title={link.node.title}>
                        {name}
                      </Link>
                    ) : (
                      <span className="truncate text-xs">{name}</span>
                    )}
                    {link.node.kind !== "module" && (
                      <span className="text-muted-foreground min-w-0 truncate text-xs">{link.node.title}</span>
                    )}
                    {link.node.status === "done" && <Badge variant="secondary">Done</Badge>}
                    {link.origin !== "derived" && (
                      <span
                        className="text-muted-foreground flex shrink-0 items-center gap-0.5 text-xs"
                        title={link.reason ?? undefined}
                      >
                        {link.origin === "agent" ? <SparklesIcon className="size-3" /> : <LinkIcon className="size-3" />}
                        {link.origin === "agent" ? `@${link.agent}` : "added"}
                      </span>
                    )}
                    {canEdit && link.origin !== "derived" && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="ml-auto size-6 shrink-0"
                        aria-label={`Remove the link to ${name}`}
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(link.id)}
                      >
                        <XIcon />
                      </Button>
                    )}
                  </dd>
                );
              })}
            </div>
          ))}
        </dl>
      )}
      {adding && <AddLinkDialog scope={scope} source={refName} onClose={() => setAdding(false)} />}
    </section>
  );
}

function AddLinkDialog({ scope, source, onClose }: { scope: Scope; source: string; onClose: () => void }) {
  const add = useAddLink(scope);
  const [target, setTarget] = useState("");
  const [kind, setKind] = useState<EdgeKind>("relates_to");
  const [reason, setReason] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate(
      { source, target: target.trim(), kind, reason: reason.trim() || null },
      { onSuccess: onClose },
    );
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Link {source}</DialogTitle>
            <DialogDescription>
              For connections the text doesn&apos;t make. Name a document by its path, an issue by its key, or a module as
              module:name.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="link-kind">How</Label>
            <select
              id="link-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as EdgeKind)}
              className="bg-background h-9 rounded-md border px-2 text-sm"
            >
              {LINKABLE.map((k) => (
                <option key={k} value={k}>
                  {LINK_LABELS[k].out}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="link-target">To</Label>
            <Input
              id="link-target"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="requirements/auth.md or KUN-12"
              required
              maxLength={300}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="link-reason">Why (optional)</Label>
            <Input id="link-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={add.isPending || !target.trim()}>
              Link
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The project's documents that may be out of date, for the Knowledge tab's side. */
export function StaleList({ scope, onOpen }: { scope: Scope; onOpen: (path: string) => void }) {
  const stale = useStale(scope);
  if (!stale.data?.length) return null;
  return (
    <details className="rounded-lg border p-2 text-xs">
      <summary className="flex cursor-pointer items-center gap-1.5 font-medium">
        <TriangleAlertIcon className="size-3.5" />
        {stale.data.length} may be out of date
      </summary>
      <ul className="mt-2 grid gap-1.5">
        {stale.data.map((s) => (
          <li key={s.node.ref}>
            <button type="button" className="font-mono hover:underline" onClick={() => onOpen(s.node.ref)}>
              {s.node.ref}
            </button>
            <p className="text-muted-foreground">{s.reasons[0]}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}
