// A coding turn's work as the side panel shows it (components/SidePanel.tsx): its diff, the repository's
// files as the turn leaves it, and the commands it ran. Desktop turns show the live worktree on this computer.
import { useEffect, useMemo, useRef, useState } from "react";

import { useCodingEvents, useCodingFile, useCodingTree, type CodingRun } from "@/lib/coding";
import type { Scope } from "@/lib/issues";

import { desktop, useDesktopRunners, worktreeHere } from "../core/desktop";
import { Ic } from "../core/icons";
import { buildTree, terminal, type DiffFile, type DiffHunk, type TreeNode } from "../core/kaiWork";
import { toast } from "../ui/toast";

const LONG_OUTPUT = 24; // lines of a command's output shown before "Show all"

/** The turn's diff, file by file. */
export function ChangesView({
  run,
  files,
  loading,
  error,
  onRetry,
}: {
  run: CodingRun;
  files: DiffFile[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  return error ? (
    <p className="muted">
      The changes couldn't be loaded.{" "}
      <button className="btn btn-sm btn-ghost" onClick={onRetry}>
        Try again
      </button>
    </p>
  ) : (
    <Changes files={files} loading={loading} turn={run} />
  );
}

/** The repository as the turn leaves it (live from the worktree when it codes on this computer). */
export function FilesView({
  scope,
  run,
  files,
  initialFile,
  initialLine,
  referenceVersion,
  enabled = true,
}: {
  scope: Scope | undefined;
  run: CodingRun;
  files: DiffFile[];
  initialFile?: string;
  initialLine?: number;
  referenceVersion?: number;
  enabled?: boolean;
}) {
  const worktree = worktreeHere(run, useDesktopRunners());
  return (
    <Files
      key={`${run.id}:${initialFile ?? ""}:${initialLine ?? ""}:${referenceVersion ?? ""}`}
      scope={scope}
      run={run}
      diffs={files}
      worktree={worktree}
      initialPath={initialFile}
      initialLine={initialLine}
      enabled={enabled}
    />
  );
}

/** Each command the turn ran, with its recorded output (read-only). */
export function TerminalView({ scope, run, enabled = true }: { scope: Scope | undefined; run: CodingRun; enabled?: boolean }) {
  const events = useCodingEvents(scope, run, enabled);
  const commands = useMemo(() => terminal(events.data ?? run.events ?? []), [events.data, run.events]);
  if (events.isLoading) return <p className="muted">Loading commands…</p>;
  if (events.isError)
    return (
      <p className="muted">
        The commands couldn't be loaded.{" "}
        <button className="btn btn-sm btn-ghost" onClick={() => void events.refetch()}>
          Try again
        </button>
      </p>
    );
  return <Terminal entries={commands} working={run.status === "running"} />;
}

/* ---------- Changes: each file's diff ---------- */

function Changes({ files, loading, turn }: { files: DiffFile[]; loading: boolean; turn: CodingRun }) {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  if (loading) return <p className="muted">Loading the changes…</p>;
  if (!files.length)
    return (
      <p className="muted">
        {turn.status === "running" || turn.status === "queued"
          ? "No changes yet: they show once the turn hands them back."
          : `Turn ${turn.turn} changed no files.`}
      </p>
    );
  const added = files.reduce((n, f) => n + f.added, 0);
  const removed = files.reduce((n, f) => n + f.removed, 0);
  return (
    <div className="kp-changes">
      <div className="row faint" style={{ gap: 8, fontSize: 12, marginBottom: 6 }}>
        {files.length} file{files.length === 1 ? "" : "s"} changed
        <span style={{ color: "var(--green)" }}>+{added}</span>
        <span style={{ color: "var(--red)" }}>-{removed}</span>
      </div>
      {files.map((f) => {
        const open = !closed.has(f.path);
        return (
          <section key={f.path} className="kp-file">
            <button
              className="kp-file-h"
              aria-expanded={open}
              onClick={() => setClosed((s) => (s.has(f.path) ? new Set([...s].filter((p) => p !== f.path)) : new Set(s).add(f.path)))}
            >
              <Ic n={open ? "chevron-down" : "chevron-right"} s={12} />
              <span className={`kp-st ${f.status}`}>{f.status === "added" ? "A" : f.status === "deleted" ? "D" : "M"}</span>
              <span className="trunc grow mono">{f.path}</span>
              <span style={{ color: "var(--green)" }}>+{f.added}</span>
              <span style={{ color: "var(--red)" }}>-{f.removed}</span>
            </button>
            {open && (f.binary ? <p className="muted kp-note">A binary file: not shown.</p> : <Hunks hunks={f.hunks} />)}
          </section>
        );
      })}
    </div>
  );
}

function Hunks({ hunks }: { hunks: DiffHunk[] }) {
  return (
    <div className="kp-diff mono" role="table" aria-label="Diff">
      {hunks.map((h, i) => (
        <div key={i}>
          <div className="kp-hunk">{h.header}</div>
          {h.lines.map((l, j) => (
            <div key={j} className={`kp-line ${l.kind}`} role="row">
              <span className="kp-no">{l.old ?? ""}</span>
              <span className="kp-no">{l.new ?? ""}</span>
              <span className="kp-sign">{l.kind === "add" ? "+" : l.kind === "del" ? "-" : " "}</span>
              <span className="kp-text">{l.text || " "}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/* ---------- Files: the repository as the turn leaves it ---------- */

function WorktreeButtons({ worktree }: { worktree: string }) {
  const act = (fn: (tree: string) => Promise<void>) => () =>
    void fn(worktree).catch((e: unknown) => toast(e instanceof Error ? e.message : "The worktree can't be opened"));
  const bridge = desktop()!;
  return (
    <>
      <button className="ibtn ibtn-sm" onClick={act(bridge.worktree.open)} aria-label="Open the worktree" data-tip={`Open ${worktree}`}>
        <Ic n="folder-open" s={14} />
      </button>
      <button className="ibtn ibtn-sm" onClick={act(bridge.worktree.reveal)} aria-label="Show the worktree in its folder" data-tip="Show in folder">
        <Ic n="external-link" s={14} />
      </button>
    </>
  );
}

function Files({
  scope,
  run,
  diffs,
  worktree,
  initialPath,
  initialLine,
  enabled,
}: {
  scope: Scope | undefined;
  run: CodingRun;
  diffs: DiffFile[];
  worktree: string | null;
  initialPath?: string;
  initialLine?: number;
  enabled: boolean;
}) {
  const tree = useCodingTree(scope, run, enabled, worktree);
  const [open, setOpen] = useState<string | null>(initialPath ?? null);
  const [changedOnly, setChangedOnly] = useState(false);
  const root = useMemo(() => buildTree((tree.data?.entries ?? []).filter((e) => !changedOnly || e.status !== "unchanged")), [tree.data, changedOnly]);
  if (open)
    return (
      <FileView
        scope={scope}
        run={run}
        path={open}
        diff={worktree ? undefined : diffs.find((d) => d.path === open)}
        worktree={worktree}
        initialLine={open === initialPath ? initialLine : undefined}
        onBack={() => setOpen(null)}
      />
    );
  if (!run.base_sha) return <p className="muted">The files show once the turn starts on a commit.</p>;
  if (tree.isLoading) return <p className="muted">Loading the files…</p>;
  if (tree.error)
    return (
      <p className="muted">
        {tree.error instanceof Error ? tree.error.message : "The files can't be read here."}{" "}
        <button className="btn btn-sm btn-ghost" onClick={() => void tree.refetch()}>
          Try again
        </button>
      </p>
    );
  return (
    <div>
      {worktree && (
        <div className="row work-file-actions">
          <span className="faint">Live on this computer</span>
          <span className="sp" />
          <WorktreeButtons worktree={worktree} />
        </div>
      )}
      <label className="row faint" style={{ gap: 6, fontSize: 12, marginBottom: 6 }}>
        <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} />
        Changed only ({root.changed})
        <span className="sp" />
        <span className="mono">{run.base_sha.slice(0, 7)}</span>
      </label>
      <div className="kp-tree mono" role="tree" aria-label="Files">
        {root.children.map((n) => (
          <Node key={n.path} node={n} depth={0} onOpen={setOpen} expanded={changedOnly} />
        ))}
      </div>
      {tree.data?.truncated && <p className="faint kp-note">Only the first 20,000 files are listed.</p>}
    </div>
  );
}

function Node({ node, depth, onOpen, expanded }: { node: TreeNode; depth: number; onOpen: (path: string) => void; expanded: boolean }) {
  const [open, setOpen] = useState(expanded || node.changed > 0);
  const pad = { paddingLeft: 6 + depth * 14 };
  if (node.file) {
    const st = node.file.status;
    return (
      <button role="treeitem" className={`kp-node file ${st}`} style={pad} onClick={() => onOpen(node.path)}>
        <Ic n="file" s={12} />
        <span className="trunc grow">{node.name}</span>
        {st !== "unchanged" && <span className={`kp-st ${st}`}>{st === "added" ? "A" : st === "deleted" ? "D" : "M"}</span>}
      </button>
    );
  }
  return (
    <div role="group">
      <button role="treeitem" aria-expanded={open} className="kp-node" style={pad} onClick={() => setOpen(!open)}>
        <Ic n={open ? "chevron-down" : "chevron-right"} s={12} />
        <Ic n={open ? "folder-open" : "folder"} s={12} />
        <span className="trunc grow">{node.name}</span>
        {node.changed > 0 && <span className="faint">{node.changed}</span>}
      </button>
      {open && node.children.map((c) => <Node key={c.path} node={c} depth={depth + 1} onOpen={onOpen} expanded={expanded} />)}
    </div>
  );
}

function FileView({
  scope,
  run,
  path,
  diff,
  worktree,
  initialLine,
  onBack,
}: {
  scope: Scope | undefined;
  run: CodingRun;
  path: string;
  diff: DiffFile | undefined;
  worktree: string | null;
  initialLine?: number;
  onBack: () => void;
}) {
  const file = useCodingFile(scope, run.id, path, worktree);
  const [view, setView] = useState<"file" | "diff">(initialLine ? "file" : diff ? "diff" : "file");
  const lineRef = useRef<HTMLDivElement>(null);
  const text = file.data?.after ?? file.data?.before ?? "";
  useEffect(() => {
    if (view === "file" && initialLine && file.data) lineRef.current?.scrollIntoView({ block: "nearest" });
  }, [file.data, initialLine, view]);
  return (
    <div>
      <div className="row" style={{ gap: 6, marginBottom: 6 }}>
        <button className="ibtn ibtn-sm" onClick={onBack} aria-label="Back to the files">
          <Ic n="arrow-left" s={13} />
        </button>
        <span className="mono trunc grow" style={{ fontSize: 12 }}>
          {path}
        </span>
        {worktree && <WorktreeButtons worktree={worktree} />}
        {diff && (
          <div className="seg seg-sm" role="tablist" aria-label="Show">
            <button role="tab" aria-selected={view === "diff"} className={view === "diff" ? "on" : ""} onClick={() => setView("diff")}>
              Diff
            </button>
            <button role="tab" aria-selected={view === "file"} className={view === "file" ? "on" : ""} onClick={() => setView("file")}>
              File
            </button>
          </div>
        )}
      </div>
      {view === "diff" && diff ? (
        diff.binary ? (
          <p className="muted">A binary file: not shown.</p>
        ) : (
          <Hunks hunks={diff.hunks} />
        )
      ) : file.isLoading ? (
        <p className="muted">Loading…</p>
      ) : file.error ? (
        <p className="muted">
          {file.error instanceof Error ? file.error.message : "This file can't be read."}{" "}
          <button className="btn btn-sm btn-ghost" onClick={() => void file.refetch()}>
            Try again
          </button>
        </p>
      ) : file.data?.binary ? (
        <p className="muted">A binary file: not shown.</p>
      ) : file.data?.too_large ? (
        <p className="muted">Over 1 MB: not shown.</p>
      ) : file.data?.status === "deleted" ? (
        <p className="muted">The turn deleted this file.</p>
      ) : (
        <div className="kp-diff mono" role="table" aria-label={path}>
          {text.split("\n").map((l, i) => (
            <div
              key={i}
              ref={i + 1 === initialLine ? lineRef : undefined}
              className={`kp-line ctx ${i + 1 === initialLine ? "kp-line-reference" : ""}`}
              role="row"
            >
              <span className="kp-no">{i + 1}</span>
              <span className="kp-text">{l || " "}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Terminal: each command with its output ---------- */

function Terminal({ entries, working }: { entries: ReturnType<typeof terminal>; working: boolean }) {
  if (!entries.length) return <p className="muted">{working ? "No commands run yet." : "It ran no commands."}</p>;
  return (
    <div className="kp-term mono" aria-label="Commands">
      {entries.map((e, i) => (
        <Command key={e.ref ?? i} entry={e} running={working && i === entries.length - 1 && e.output === null} />
      ))}
    </div>
  );
}

function Command({ entry, running }: { entry: ReturnType<typeof terminal>[number]; running: boolean }) {
  const [all, setAll] = useState(false);
  const lines = (entry.output ?? "").split("\n");
  const shown = all ? lines : lines.slice(-LONG_OUTPUT);
  return (
    <div className={`kp-cmd ${entry.failed ? "failed" : ""}`}>
      <div className="kp-prompt">
        <span className="kp-dollar">$</span>
        <span className="grow">
          {entry.command}
          {running && <span className="faint"> …</span>}
        </span>
        {entry.failed && <Ic n="triangle-alert" s={12} cls="kp-fail" />}
      </div>
      {entry.output !== null && entry.output !== "" && (
        <>
          {!all && lines.length > LONG_OUTPUT && (
            <button className="kp-more" onClick={() => setAll(true)}>
              Show all {lines.length} lines
            </button>
          )}
          <pre className="kp-out">{shown.join("\n")}</pre>
        </>
      )}
    </div>
  );
}
