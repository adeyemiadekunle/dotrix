// A coding turn's work as the side panel shows it (components/SidePanel.tsx): its diff, the repository's
// files as the turn leaves it, and the commands it ran. Desktop turns show the live worktree on this computer.
import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@dotrix/ui/components/collapsible";
import { languageOf, useHighlight, type HighlightToken } from "@dotrix/ui/hooks/use-highlight";

import { useCodingEvents, useCodingFile, useCodingTree, type CodingRun } from "@/lib/coding";
import type { Scope } from "@/lib/issues";

import { desktop, useDesktopRunners, worktreeHere } from "../core/desktop";
import { Ic } from "../core/icons";
import { OutputReading } from "./AgentTrace";
import { buildTree, fileIcon, terminal, type DiffFile, type DiffHunk, type TreeNode } from "../core/kaiWork";
import { toast } from "../ui/toast";

const LONG_OUTPUT = 24; // lines of a command's output shown before "Show all"

/** A note on one line of the new file (Juno's finding), shown under that line in the diff. */
export interface DiffNote {
  line: number;
  title: string;
  severity: string;
}

/** The turn's diff, file by file, with any notes on their lines. */
export function ChangesView({
  run,
  files,
  loading,
  error,
  onRetry,
  notes,
  onNote,
}: {
  run: CodingRun;
  files: DiffFile[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  notes?: Map<string, DiffNote[]>;
  onNote?: () => void;
}) {
  return error ? (
    <p className="muted">
      The changes couldn't be loaded.{" "}
      <button className="btn btn-sm btn-ghost" onClick={onRetry}>
        Try again
      </button>
    </p>
  ) : (
    <ChangeList files={files} loading={loading} turn={run} notes={notes} onNote={onNote} />
  );
}

/** The repository as the turn leaves it (live from the worktree when it codes on this computer): its files' contents.
 *  What the turn changed in them is Changes' to show. */
export function FilesView({
  scope,
  run,
  initialFile,
  initialLine,
  referenceVersion,
  enabled = true,
}: {
  scope: Scope | undefined;
  run: CodingRun;
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
  return <CommandList entries={commands} working={run.status === "running"} />;
}

/* ---------- Changes: each file's diff ---------- */

export function ChangeList({
  files,
  loading,
  turn,
  notes,
  onNote,
}: {
  files: DiffFile[];
  loading: boolean;
  turn: Pick<CodingRun, "status" | "turn">;
  notes?: Map<string, DiffNote[]>;
  onNote?: () => void;
}) {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const [viewed, setViewed] = useState<Set<string>>(new Set());
  const toggle = (set: Set<string>, path: string) => (set.has(path) ? new Set([...set].filter((p) => p !== path)) : new Set(set).add(path));
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
        {viewed.size > 0 && (
          <span className="sp" style={{ textAlign: "right" }}>
            {viewed.size} of {files.length} viewed
          </span>
        )}
      </div>
      {files.map((f) => {
        const seen = viewed.has(f.path);
        const open = !closed.has(f.path) && !seen;
        return (
          <section key={f.path} className={`kp-file ${seen ? "seen" : ""}`}>
            <div className="kp-file-row">
              <button className="kp-file-h" aria-expanded={open} onClick={() => setClosed((s) => toggle(s, f.path))}>
                <Ic n={open ? "chevron-down" : "chevron-right"} s={12} />
                <span className={`kp-st ${f.status}`}>{f.status === "added" ? "A" : f.status === "deleted" ? "D" : "M"}</span>
                <span className="trunc grow mono">{f.path}</span>
                {!!notes?.get(f.path)?.length && (
                  <span className="kp-note-count" title="Juno's findings on this file">
                    <Ic n="shield-check" s={11} />
                    {notes.get(f.path)!.length}
                  </span>
                )}
                <span style={{ color: "var(--green)" }}>+{f.added}</span>
                <span style={{ color: "var(--red)" }}>-{f.removed}</span>
              </button>
              <button
                className={`kp-viewed ${seen ? "on" : ""}`}
                onClick={() => setViewed((s) => toggle(s, f.path))}
                aria-pressed={seen}
                aria-label={seen ? `Mark ${f.path} as not viewed` : `Mark ${f.path} as viewed`}
                data-tip={seen ? "Viewed" : "Mark as viewed"}
              >
                <Ic n={seen ? "circle-check" : "circle"} s={15} />
              </button>
            </div>
            {open &&
              (f.binary ? (
                <p className="muted kp-note">A binary file: not shown.</p>
              ) : (
                <Hunks hunks={f.hunks} path={f.path} notes={notes?.get(f.path)} onNote={onNote} />
              ))}
          </section>
        );
      })}
    </div>
  );
}

/** A line's text, coloured when its tokens are known. */
function Code({ text, tokens }: { text: string; tokens?: HighlightToken[] }) {
  if (!tokens?.length || tokens.map((t) => t.content).join("") !== text) return <>{text || " "}</>;
  return (
    <>
      {tokens.map((t, i) => (
        <span key={i} className="kp-tok" style={t.style}>
          {t.content}
        </span>
      ))}
    </>
  );
}

/** A diff's hunks, coloured as Claude Code's diff is: each side's lines highlighted together (the new side for added and
 *  unchanged lines, the old side for removed ones), so the code reads as code. */
function Hunks({ hunks, path, notes = [], onNote }: { hunks: DiffHunk[]; path?: string; notes?: DiffNote[]; onNote?: () => void }) {
  const sides = useMemo(() => {
    const after: string[] = [];
    const before: string[] = [];
    const at = hunks.map((h) =>
      h.lines.map((l) => {
        const place = l.kind === "del" ? before.length : after.length;
        if (l.kind !== "del") after.push(l.text);
        if (l.kind !== "add") before.push(l.text);
        return l.kind === "ctx" ? { after: after.length - 1 } : l.kind === "add" ? { after: place } : { before: place };
      }),
    );
    return { after: after.join("\n"), before: before.join("\n"), at };
  }, [hunks]);
  const language = path ? languageOf(path) : undefined;
  const afterTokens = useHighlight(sides.after, language);
  const beforeTokens = useHighlight(sides.before, language);
  return (
    <div className="kp-diff mono" role="table" aria-label="Diff">
      {hunks.map((h, i) => (
        <div key={i}>
          <div className="kp-hunk">{h.header}</div>
          {h.lines.map((l, j) => {
            const place = sides.at[i]![j]!;
            const tokens = "before" in place ? beforeTokens?.[place.before!] : afterTokens?.[place.after!];
            return (
              <Fragment key={j}>
                <div className={`kp-line ${l.kind}`} role="row">
                  <span className="kp-no">{l.old ?? ""}</span>
                  <span className="kp-no">{l.new ?? ""}</span>
                  <span className="kp-sign">{l.kind === "add" ? "+" : l.kind === "del" ? "-" : " "}</span>
                  <span className="kp-text">
                    <Code text={l.text} tokens={tokens} />
                  </span>
                </div>
                {l.kind !== "del" &&
                  notes
                    .filter((n) => n.line === l.new)
                    .map((n, k) => (
                      <button key={k} className="kp-finding" onClick={onNote} aria-label={`Juno's finding on line ${n.line}: ${n.title}`}>
                        <Ic n="shield-check" s={12} />
                        <b>Juno</b>
                        {n.severity && <span className="badge">{n.severity}</span>}
                        <span className="trunc">{n.title}</span>
                      </button>
                    ))}
              </Fragment>
            );
          })}
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
  worktree,
  initialPath,
  initialLine,
  enabled,
}: {
  scope: Scope | undefined;
  run: CodingRun;
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
      <FileTree nodes={root.children} onOpen={setOpen} expanded={changedOnly} />
      {tree.data?.truncated && <p className="faint kp-note">Only the first 20,000 files are listed.</p>}
    </div>
  );
}

export function FileTree({ nodes, onOpen, expanded = false }: { nodes: TreeNode[]; onOpen: (path: string) => void; expanded?: boolean }) {
  return (
    <div className="kp-tree mono" role="tree" aria-label="Files">
      {nodes.map((node) => (
        <Node key={node.path} node={node} depth={0} onOpen={onOpen} expanded={expanded} />
      ))}
    </div>
  );
}

/** A folder opens and closes as a Collapsible (shadcn's AI Elements File Tree); changed folders start open. */
function Node({ node, depth, onOpen, expanded }: { node: TreeNode; depth: number; onOpen: (path: string) => void; expanded: boolean }) {
  const [open, setOpen] = useState(expanded || node.changed > 0);
  const pad = { paddingLeft: 6 + depth * 14 };
  if (node.file) {
    const st = node.file.status;
    return (
      <button role="treeitem" className={`kp-node file ${st}`} style={pad} onClick={() => onOpen(node.path)} title={node.path}>
        <Ic n={fileIcon(node.path)} s={13} cls="kp-file-icon" />
        <span className="trunc grow">{node.name}</span>
        {st !== "unchanged" && (
          <span className={`kp-st ${st}`} aria-label={st}>
            {st === "added" ? "A" : st === "deleted" ? "D" : "M"}
          </span>
        )}
      </button>
    );
  }
  return (
    <Collapsible open={open} onOpenChange={setOpen} role="group">
      <CollapsibleTrigger role="treeitem" className="kp-node kp-folder" style={pad} title={node.path}>
        <Ic n="chevron-right" s={12} cls="kp-chev" />
        <Ic n={open ? "folder-open" : "folder"} s={12} />
        <span className="trunc grow">{node.name}</span>
        {node.changed > 0 && <span className="faint">{node.changed}</span>}
      </CollapsibleTrigger>
      <CollapsibleContent>
        {node.children.map((c) => (
          <Node key={c.path} node={c} depth={depth + 1} onOpen={onOpen} expanded={expanded} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

const STATUS_SAID: Record<string, string> = { added: "Added", deleted: "Deleted", modified: "Modified" };

/** A file as Claude Code's file view shows it: its path as a breadcrumb under the file's icon, whether the turn changed
 *  it, Copy path; then its content with line numbers, highlighted (the line a reference names marked). Its diff is in
 *  Changes. */
function FileView({
  scope,
  run,
  path,
  worktree,
  initialLine,
  onBack,
}: {
  scope: Scope | undefined;
  run: CodingRun;
  path: string;
  worktree: string | null;
  initialLine?: number;
  onBack: () => void;
}) {
  const file = useCodingFile(scope, run.id, path, worktree, run.status === "running");
  const lineRef = useRef<HTMLDivElement>(null);
  const text = file.data?.after ?? file.data?.before ?? "";
  const tokens = useHighlight(text, languageOf(path));
  useEffect(() => {
    if (initialLine && file.data) lineRef.current?.scrollIntoView({ block: "nearest" });
  }, [file.data, initialLine]);
  const parts = path.split("/");
  const status = file.data?.status && file.data.status !== "unchanged" ? file.data.status : null;
  const copyPath = () =>
    void navigator.clipboard
      ?.writeText(path)
      .then(() => toast("Path copied"))
      .catch(() => toast("It couldn't be copied"));
  return (
    <div className="kp-fileview">
      <div className="kp-file-bar">
        <button className="ibtn ibtn-sm" onClick={onBack} aria-label="Back to the files">
          <Ic n="arrow-left" s={13} />
        </button>
        <Ic n={fileIcon(path)} s={14} cls="kp-file-icon" />
        <span className="kp-crumbs mono" title={path}>
          {parts.map((part, i) => (
            <Fragment key={i}>
              {i > 0 && <span className="kp-crumb-sep">/</span>}
              <span className={i === parts.length - 1 ? "kp-crumb-file" : "kp-crumb"}>{part}</span>
            </Fragment>
          ))}
        </span>
        {status && (
          <span className={`kp-st ${status}`} title={STATUS_SAID[status]} aria-label={STATUS_SAID[status]}>
            {status === "added" ? "A" : status === "deleted" ? "D" : "M"}
          </span>
        )}
        <span className="sp" />
        {worktree && <WorktreeButtons worktree={worktree} />}
        <button className="ibtn ibtn-sm" onClick={copyPath} aria-label="Copy the path" data-tip="Copy path">
          <Ic n="copy" s={13} />
        </button>
      </div>
      {file.isLoading ? (
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
        <div className="kp-source mono" role="table" aria-label={path}>
          {(text.endsWith("\n") ? text.slice(0, -1) : text).split("\n").map((l, i) => (
            <div
              key={i}
              ref={i + 1 === initialLine ? lineRef : undefined}
              className={`kp-src-line ${i + 1 === initialLine ? "kp-line-reference" : ""}`}
              role="row"
            >
              <span className="kp-no">{i + 1}</span>
              <span className="kp-text">
                <Code text={l} tokens={tokens?.[i]} />
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Terminal: each command with its output ---------- */

export function CommandList({ entries, working }: { entries: ReturnType<typeof terminal>; working: boolean }) {
  if (!entries.length) return <p className="muted">{working ? "No commands run yet." : "It ran no commands."}</p>;
  return (
    <div className="kp-term mono" aria-label="Commands">
      {entries.map((e, i) => (
        <Command key={e.ref ?? i} entry={e} running={working && i === entries.length - 1 && e.output === null} />
      ))}
    </div>
  );
}

/** Terminal: one command as it ran, a mark for how it ended, its output, and that output read (Test Results and
 *  Stack Trace) when it's a test run or a crash. */
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
        {running ? (
          <Ic n="spinner-gap" s={12} cls="animate-spin" />
        ) : entry.failed ? (
          <Ic n="triangle-alert" s={12} cls="kp-fail" />
        ) : entry.output !== null ? (
          <Ic n="check" s={12} cls="kp-ok" />
        ) : null}
      </div>
      {!running && entry.output && <OutputReading text={entry.output} failed={entry.failed} />}
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
