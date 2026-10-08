import { Button } from "@pmagent/ui/components/button";
import { Input } from "@pmagent/ui/components/input";
import { cn } from "@pmagent/ui/lib/utils";
import { PencilIcon } from "lucide-react";
import { useState } from "react";

import { runTitle, useRenameThread, useThread } from "@/lib/agent";
import type { Scope } from "@/lib/issues";

/** A conversation's title; click it (or the pencil) to rename. Nothing for a new conversation. */
export function ThreadTitle({
  scope,
  threadId,
  className,
  fallback,
}: {
  scope: Scope;
  threadId: string | null;
  className?: string;
  fallback?: string;
}) {
  const thread = useThread(scope, threadId);
  const rename = useRenameThread(scope);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const first = thread.data?.[0];
  const title = first ? (first.title ?? runTitle(first)) : null;

  if (!threadId || !title) {
    return fallback ? <span className={cn("truncate text-sm font-medium", className)}>{fallback}</span> : null;
  }

  async function save() {
    const next = draft.trim();
    setEditing(false);
    if (next && next !== title && threadId) await rename.mutateAsync({ threadId, title: next }).catch(() => undefined);
  }

  if (editing) {
    return (
      <Input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setEditing(false);
        }}
        maxLength={120}
        className={cn("h-7 text-sm", className)}
        aria-label="Conversation title"
        autoFocus
      />
    );
  }
  return (
    <span className={cn("group flex min-w-0 items-center gap-1", className)}>
      <button
        type="button"
        className="truncate text-left text-sm font-medium"
        title="Rename"
        onClick={() => {
          setDraft(title);
          setEditing(true);
        }}
      >
        {title}
      </button>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="size-6 shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
        aria-label="Rename conversation"
        onClick={() => {
          setDraft(title);
          setEditing(true);
        }}
      >
        <PencilIcon className="size-3.5" />
      </Button>
    </span>
  );
}
