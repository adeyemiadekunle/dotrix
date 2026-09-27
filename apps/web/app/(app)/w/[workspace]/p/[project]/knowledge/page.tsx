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
import { Input } from "@pmagent/ui/components/input";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Textarea } from "@pmagent/ui/components/textarea";
import { cn } from "@pmagent/ui/lib/utils";
import {
  BookOpenIcon,
  CodeIcon,
  DownloadIcon,
  FilePlusIcon,
  HistoryIcon,
  LockIcon,
  PencilIcon,
  SearchIcon,
  Trash2Icon,
} from "lucide-react";
import { Suspense, useMemo, useState, type FormEvent } from "react";

import { Field, SubmitButton } from "@/components/form";
import { timeAgo } from "@/components/issues/issue-activity";
import { FileHistory } from "@/components/knowledge/file-history";
import { FileTree } from "@/components/knowledge/file-tree";
import { Markdown } from "@/components/markdown";
import { EmptyState } from "@/components/states";
import { useMembers, type Scope } from "@/lib/issues";
import {
  buildTree,
  exportUrl,
  isAgentRules,
  useDeleteFile,
  useFile,
  useManifest,
  useWriteFile,
  type FileEntry,
} from "@/lib/knowledge";
import { canManageProjects } from "@/lib/labels";
import { useProjectScope } from "@/lib/queries";
import { useSearchParam, useSetSearchParams } from "@/lib/url-state";

function Editor({
  scope,
  path,
  content,
  version,
  onDone,
}: {
  scope: Scope;
  path: string;
  content: string;
  version: number;
  onDone: () => void;
}) {
  const write = useWriteFile(scope);
  const [draft, setDraft] = useState(content);
  const [message, setMessage] = useState("");
  return (
    <form
      className="grid gap-3"
      onSubmit={async (e: FormEvent) => {
        e.preventDefault();
        // base_version: if someone changed the file meanwhile, the API refuses (409) instead of
        // overwriting their change. Close from the promise, not a mutate callback: the saved
        // version remounts this editor (its key), which would drop the callback.
        const saved = await write
          .mutateAsync({ path, content: draft, baseVersion: version, message })
          .catch(() => null);
        if (saved) onDone();
      }}
    >
      <Textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="min-h-[50svh] font-mono text-xs leading-relaxed"
        spellCheck={false}
        aria-label={`Edit ${path}`}
        autoFocus
      />
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="What changed? (optional, shown in history)"
          className="h-9 min-w-48 flex-1"
          maxLength={500}
        />
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <SubmitButton pending={write.isPending} disabled={write.isPending || draft === content}>
          Save
        </SubmitButton>
      </div>
    </form>
  );
}

function FilePane({
  scope,
  entry,
  names,
  canEdit,
  onDeleted,
}: {
  scope: Scope;
  entry: FileEntry;
  names: Map<string, string>;
  canEdit: boolean;
  onDeleted: () => void;
}) {
  const path = entry.path;
  const file = useFile(scope, entry.deleted ? null : path);
  const remove = useDeleteFile(scope);
  const [version, setVersion] = useSearchParam("v");
  const [editing, setEditing] = useState(false);
  const [source, setSource] = useState(false);
  const [showHistory, setShowHistory] = useState(entry.deleted);
  const [confirming, setConfirming] = useState(false);
  const isMarkdown = /\.(md|markdown)$/i.test(path);
  const rules = isAgentRules(path);

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="min-w-0 flex-1 truncate font-mono text-sm font-medium" title={path}>
          {path}
        </h2>
        {entry.deleted ? (
          <Badge variant="secondary">Deleted</Badge>
        ) : (
          <span className="text-muted-foreground text-xs">
            v{entry.version} · updated {timeAgo(entry.updated_at)}
          </span>
        )}
      </div>

      {rules && (
        <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <LockIcon className="size-3.5" />
          Agent rules shape how the agents behave. Only owners and admins change them.
        </p>
      )}

      {!editing && (
        <div className="flex flex-wrap gap-2">
          {!entry.deleted && canEdit && (
            <Button size="sm" variant="outline" onClick={() => setEditing(true)} disabled={!file.data}>
              <PencilIcon />
              Edit
            </Button>
          )}
          {!entry.deleted && isMarkdown && (
            <Button size="sm" variant="ghost" onClick={() => setSource((s) => !s)} aria-pressed={source}>
              {source ? <BookOpenIcon /> : <CodeIcon />}
              {source ? "Rendered" : "Source"}
            </Button>
          )}
          <Button
            size="sm"
            variant={showHistory ? "secondary" : "ghost"}
            onClick={() => {
              setShowHistory((h) => !h);
              setVersion(null);
            }}
            aria-pressed={showHistory}
          >
            <HistoryIcon />
            History
          </Button>
          {!entry.deleted && canEdit && (
            <Button
              size="sm"
              variant="ghost"
              className="text-destructive hover:text-destructive ml-auto"
              disabled={remove.isPending}
              onClick={() => setConfirming(true)}
            >
              <Trash2Icon />
              Delete
            </Button>
          )}
        </div>
      )}

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete this file?</DialogTitle>
            <DialogDescription>
              <code className="font-mono">{path}</code> stays in the history, so you can restore it later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(
                  { path, baseVersion: entry.version },
                  {
                    onSuccess: () => {
                      setConfirming(false);
                      onDeleted();
                    },
                  },
                )
              }
            >
              Delete file
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {showHistory && (
        <FileHistory
          scope={scope}
          path={path}
          currentVersion={entry.version}
          deleted={entry.deleted}
          selected={version ? Number(version) : null}
          onSelect={(v) => setVersion(v === null ? null : String(v))}
          names={names}
          canRestore={canEdit}
        />
      )}

      {entry.deleted ? (
        <p className="text-muted-foreground text-sm">
          This file was deleted. Pick an earlier version in the history to see it or restore it.
        </p>
      ) : file.isLoading ? (
        <Skeleton className="h-64" />
      ) : file.isError ? (
        <p className="text-muted-foreground text-sm">Couldn&apos;t load this file.</p>
      ) : file.data && editing ? (
        <Editor
          key={file.data.version}
          scope={scope}
          path={path}
          content={file.data.content}
          version={file.data.version}
          onDone={() => setEditing(false)}
        />
      ) : file.data && !showHistory ? (
        file.data.content.trim() === "" ? (
          <p className="text-muted-foreground text-sm">This file is empty.</p>
        ) : isMarkdown && !source ? (
          <div className="rounded-lg border p-4 md:p-6">
            <Markdown>{file.data.content}</Markdown>
          </div>
        ) : (
          <pre className="bg-muted/40 overflow-x-auto rounded-lg border p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
            {file.data.content}
          </pre>
        )
      ) : null}
    </div>
  );
}

function NewFileDialog({
  scope,
  open,
  onOpenChange,
  onCreated,
}: {
  scope: Scope;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (path: string) => void;
}) {
  const write = useWriteFile(scope);
  const [path, setPath] = useState("");
  const clean = path.trim().replace(/^\/+/, "").replace(/^\.pmagent\//, "");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            write.mutate(
              { path: clean, content: `# ${clean.split("/").at(-1)?.replace(/\.md$/, "")}\n`, baseVersion: null },
              {
                onSuccess: () => {
                  onOpenChange(false);
                  setPath("");
                  onCreated(clean);
                },
              },
            );
          }}
        >
          <DialogHeader>
            <DialogTitle>New file</DialogTitle>
            <DialogDescription>A path inside the project&apos;s knowledge. Folders are created as needed.</DialogDescription>
          </DialogHeader>
          <Field
            label="Path"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="research/competitors.md"
            required
            pattern="[^\s].*\.[A-Za-z0-9]+"
            className="font-mono"
            hint="Markdown (.md) is best for documents the agents read."
            autoFocus
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={write.isPending}>Create</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function KnowledgePage() {
  const { workspace, scope } = useProjectScope();
  const manifest = useManifest(scope);
  const members = useMembers(workspace?.id);
  const names = useMemo(() => new Map(members.data?.map((m) => [m.user_id, m.display_name])), [members.data]);
  const [selected] = useSearchParam("file");
  const setParams = useSetSearchParams();
  const [query, setQuery] = useState("");
  const [showDeleted, setShowDeleted] = useState(false);
  const [creating, setCreating] = useState(false);
  const role = workspace?.role;
  const canEditKnowledge = role !== undefined && role !== "guest";
  const isAdmin = canManageProjects(role);

  const files = manifest.data?.files ?? [];
  const visible = files.filter(
    (f) => (showDeleted || !f.deleted) && (!query || f.path.toLowerCase().includes(query.toLowerCase())),
  );
  const tree = useMemo(() => buildTree(visible), [visible]);
  const entry = files.find((f) => f.path === selected) ?? null;
  const deletedCount = files.filter((f) => f.deleted).length;

  function open(path: string) {
    setParams({ file: path, v: null });
  }

  return (
    // Tree beside the file when there's room, above it when narrow (container queries).
    <div className="@container flex-1">
      <div className="grid gap-4 p-4 md:p-6 @3xl:grid-cols-[16rem_minmax(0,1fr)] @3xl:items-start">
        <aside className="grid content-start gap-3 @3xl:sticky @3xl:top-4">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <SearchIcon className="text-muted-foreground absolute top-2.5 left-2.5 size-4" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Find a file"
                className="h-9 pl-8"
                aria-label="Find a file"
              />
            </div>
            {canEditKnowledge && scope && (
              <Button size="icon" variant="outline" className="size-9" onClick={() => setCreating(true)} aria-label="New file">
                <FilePlusIcon />
              </Button>
            )}
          </div>
          <div className="max-h-[40svh] overflow-y-auto rounded-lg border p-1 @3xl:max-h-[calc(100svh-14rem)]">
            {manifest.isLoading ? (
              <Skeleton className="h-48" />
            ) : tree.length ? (
              <FileTree nodes={tree} selected={selected} onSelect={open} filtering={Boolean(query)} />
            ) : (
              <p className="text-muted-foreground p-2 text-xs">No files match.</p>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            {deletedCount > 0 ? (
              <label className="text-muted-foreground flex items-center gap-1.5">
                <input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
                Show {deletedCount} deleted
              </label>
            ) : (
              <span />
            )}
            {isAdmin && scope && (
              <a href={exportUrl(scope)} className="text-muted-foreground hover:text-foreground flex items-center gap-1" download>
                <DownloadIcon className="size-3.5" />
                Export all (zip)
              </a>
            )}
          </div>
          {manifest.data && (
            <p className="text-muted-foreground text-xs">
              {files.length - deletedCount} files · revision {manifest.data.revision}
            </p>
          )}
        </aside>

        <div className={cn("min-w-0", !entry && "self-stretch")}>
          {scope && entry ? (
            <FilePane
              key={entry.path}
              scope={scope}
              entry={entry}
              names={names}
              canEdit={canEditKnowledge && (!isAgentRules(entry.path) || isAdmin)}
              onDeleted={() => setShowDeleted(true)}
            />
          ) : (
            <EmptyState
              icon={BookOpenIcon}
              title="The project's knowledge"
              description="Requirements, architecture, decisions, research, and progress: the files the agents read and write, with every version kept. Pick a file to read it."
            />
          )}
        </div>
      </div>
      {scope && <NewFileDialog scope={scope} open={creating} onOpenChange={setCreating} onCreated={open} />}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <KnowledgePage />
    </Suspense>
  );
}
