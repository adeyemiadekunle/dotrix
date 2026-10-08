import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { BotIcon, HistoryIcon, RotateCcwIcon, UserIcon } from "lucide-react";

import { DiffView } from "@/components/agent/approvals";
import { timeAgo } from "@/components/issues/issue-activity";
import type { Scope } from "@/lib/issues";
import { useRestoreVersion, useVersionDiff, useVersions, type VersionEntry } from "@/lib/knowledge";
import { agentName } from "@/lib/labels";

/** Who wrote a version, and for agent writes, who asked and who approved. */
export function authorship(v: VersionEntry, names: Map<string, string>): { who: string; agent: boolean; detail?: string } {
  const person = (id: string | null) => (id ? (names.get(id) ?? "a former member") : null);
  if (v.author_type === "agent") {
    const parts = [
      person(v.instructed_by_id) && `asked by ${person(v.instructed_by_id)}`,
      person(v.approved_by_id) && `approved by ${person(v.approved_by_id)}`,
    ].filter(Boolean);
    return { who: agentName(v.agent), agent: true, detail: parts.join(", ") || undefined };
  }
  if (v.author_type === "system") return { who: "dotrix", agent: false, detail: "project setup or import" };
  return { who: person(v.author_id) ?? "Someone", agent: false };
}

/**
 * A file's versions, newest first. Selecting one shows what it changed; restoring makes it
 * current again as a new version, so nothing is lost.
 */
export function FileHistory({
  scope,
  path,
  currentVersion,
  deleted,
  selected,
  onSelect,
  names,
  canRestore,
}: {
  scope: Scope;
  path: string;
  currentVersion: number | null;
  /** The file is deleted now; restoring recreates it (the API counts a deleted file as version 0). */
  deleted: boolean;
  selected: number | null;
  onSelect: (version: number | null) => void;
  names: Map<string, string>;
  canRestore: boolean;
}) {
  const versions = useVersions(scope, path, true);
  const diff = useVersionDiff(scope, path, selected);
  const restore = useRestoreVersion(scope);

  return (
    <section className="grid gap-3">
      <h3 className="flex items-center gap-1.5 text-sm font-medium">
        <HistoryIcon className="size-4" />
        History
      </h3>
      {versions.isLoading && <Skeleton className="h-24" />}
      <ol className="grid gap-1">
        {versions.data?.map((v) => {
          const a = authorship(v, names);
          const isSelected = selected === v.version;
          return (
            <li key={v.version}>
              <button
                type="button"
                onClick={() => onSelect(isSelected ? null : v.version)}
                aria-pressed={isSelected}
                className={cn(
                  "hover:bg-muted grid w-full gap-0.5 rounded-md border px-3 py-2 text-left text-sm",
                  isSelected && "border-primary bg-muted",
                )}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="font-mono text-[10px]">
                    v{v.version}
                  </Badge>
                  {a.agent ? <BotIcon className="text-brand size-3.5" /> : <UserIcon className="text-muted-foreground size-3.5" />}
                  <span className="font-medium">{a.who}</span>
                  {v.deleted && <Badge variant="secondary">Deleted</Badge>}
                  {v.version === currentVersion && <Badge variant="secondary">Current</Badge>}
                  <span className="text-muted-foreground ml-auto text-xs">{timeAgo(v.created_at)}</span>
                </span>
                {(a.detail || v.message) && (
                  <span className="text-muted-foreground text-xs">
                    {[v.message, a.detail].filter(Boolean).join(" · ")}
                  </span>
                )}
              </button>
              {isSelected && (
                <div className="grid gap-2 py-2">
                  {diff.isLoading && <Skeleton className="h-24" />}
                  {diff.data &&
                    (diff.data.diff ? (
                      <DiffView diff={diff.data.diff} />
                    ) : (
                      <p className="text-muted-foreground text-xs">No text changes in this version.</p>
                    ))}
                  {canRestore && !v.deleted && v.version !== currentVersion && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="justify-self-start"
                      disabled={restore.isPending}
                      onClick={() =>
                        restore.mutate(
                          { path, version: v.version, baseVersion: deleted ? 0 : currentVersion },
                          { onSuccess: () => onSelect(null) },
                        )
                      }
                    >
                      <RotateCcwIcon />
                      Restore v{v.version}
                    </Button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
