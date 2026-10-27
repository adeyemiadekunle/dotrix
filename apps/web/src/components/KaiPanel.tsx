// Kai's work beside a conversation or a session: the turn's Changes (each file's diff), its Files (the
// repository as the turn leaves it, any file before and after), and its Terminal (each command with its
// output). The same for cloud and local turns: everything comes from the platform (lib/coding.ts), except
// a turn coding on this computer in the desktop app, whose Files are its worktree as it is now
// (core/desktop.ts), with the folder a click away.
import { useMemo, useState, type ReactNode } from "react";

import { useCodingDiff, useCodingEvents, useCodingFile, useCodingSession, useCodingTree, type CodingRun, type CodingSession } from "@/lib/coding";

import { desktop, useDesktopRunners, worktreeHere } from "../core/desktop";
import { Ic } from "../core/icons";
import { buildTree, parseDiff, terminal, type DiffFile, type DiffHunk, type TreeNode } from "../core/kaiWork";
import { CODING_AGENT } from "../data/seed-dotrix";
import { live } from "../data/live";
import { toast } from "../ui/toast";
import { Splitter, useStoredSize } from "../ui/splitter";

type Tab = "changes" | "files" | "terminal";
const LONG_OUTPUT = 24; // lines of a command's output shown before "Show all"

export function KaiPanel({
  cs,
  onClose,
  navigation,
  initialTurn,
  initialFile,
}: {
  cs: CodingSession;
  onClose: () => void;
  navigation?: ReactNode;
  initialTurn?: string;
  initialFile?: string;
}) {
  const ws = live.ws?.id;
  const scope = useMemo(() => (ws ? { workspaceId: ws, projectId: cs.project_id } : undefined), [ws, cs.project_id]);
  const turns = useCodingSession(scope, cs.session_id).data ?? [];
  const [picked, setPicked] = useState<string | null>(initialTurn ?? null);
  const run = turns.find((t) => t.id === picked) ?? turns.at(-1);
  const [tab, setTab] = useState<Tab>(initialFile ? "files" : "changes");
  const [width, setWidth] = useStoredSize("dotrix.chat.kaiPanel.width", 420, 300, 900);
  const diff = useCodingDiff(scope, run);
  const files = useMemo(() => parseDiff(diff.data?.diff ?? ""), [diff.data?.diff]);
  const events = useCodingEvents(scope, run, tab === "terminal");
  const commands = useMemo(() => terminal(events.data ?? run?.events ?? []), [events.data, run?.events]);
  const worktree = worktreeHere(run, useDesktopRunners());
  const TABS: [Tab, string, number][] = [
    ["changes", "Changes", files.length],
    ["files", "Files", 0],
    ["terminal", "Terminal", commands.length],
  ];
  return (
    <aside className="kai-panel" style={{ width }} aria-label={`${CODING_AGENT.name}'s work`}>
      <Splitter dir="col" className="kai-panel-split" label="Resize the panel" onDrag={(d) => setWidth((w) => w - d)} />
      {navigation}
      <div className="row" style={{ height: 46, padding: "0 12px", borderBottom: "1px solid var(--border)", gap: 8, flexShrink: 0 }}>
        <b className="trunc" style={{ fontWeight: 600, fontSize: 13 }}>
          {CODING_AGENT.name} · <span className="mono">{cs.issue_key}</span>
        </b>
        <span className="sp" />
        {turns.length > 1 && run && (
          <select className="input input-sm" value={run.id} onChange={(e) => setPicked(e.target.value)} aria-label="Turn">
            {turns.map((t) => (
              <option key={t.id} value={t.id}>
                Turn {t.turn}
              </option>
            ))}
          </select>
        )}
        {worktree && <WorktreeButtons worktree={worktree} />}
        <button className="ibtn ibtn-sm" onClick={onClose} aria-label="Close the panel">
          <Ic n="x" s={14} />
        </button>
      </div>
      <div className="seg" role="tablist" aria-label="Kai's work" style={{ margin: "8px 12px" }}>
        {TABS.map(([id, label, n]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
            {label}
            {n > 0 && <span className="faint"> {n}</span>}
          </button>
        ))}
      </div>
      <div className="kai-panel-body">
        {!run ? (
          <p className="muted">Nothing yet.</p>
        ) : tab === "changes" ? (
          <Changes files={files} loading={diff.isLoading} turn={run} />
        ) : tab === "files" ? (
          <Files scope={scope} run={run} diffs={files} worktree={worktree} initialPath={initialFile} />
        ) : (
          <Terminal entries={commands} working={run.status === "running"} />
        )}
      </div>
    </aside>
  );
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
}: {
  scope: { workspaceId: string; projectId: string } | undefined;
  run: CodingRun;
  diffs: DiffFile[];
  worktree: string | null;
  initialPath?: string;
}) {
  const tree = useCodingTree(scope, run, true, worktree);
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
        onBack={() => setOpen(null)}
      />
    );
  if (!run.base_sha) return <p className="muted">The files show once the turn starts on a commit.</p>;
  if (tree.isLoading) return <p className="muted">Loading the files…</p>;
  if (tree.error) return <p className="muted">{tree.error instanceof Error ? tree.error.message : "The files can't be read here."}</p>;
  return (
    <div>
      <label className="row faint" style={{ gap: 6, fontSize: 12, marginBottom: 6 }}>
        <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} />
        Changed only ({root.changed})
        <span className="sp" />
        {worktree && <span data-tip={worktree}>Live on this computer ·</span>}
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
  onBack,
}: {
  scope: { workspaceId: string; projectId: string } | undefined;
  run: CodingRun;
  path: string;
  diff: DiffFile | undefined;
  worktree: string | null;
  onBack: () => void;
}) {
  const file = useCodingFile(scope, run.id, path, worktree);
  const [view, setView] = useState<"file" | "diff">(diff ? "diff" : "file");
  const text = file.data?.after ?? file.data?.before ?? "";
  return (
    <div>
      <div className="row" style={{ gap: 6, marginBottom: 6 }}>
        <button className="ibtn ibtn-sm" onClick={onBack} aria-label="Back to the files">
          <Ic n="arrow-left" s={13} />
        </button>
        <span className="mono trunc grow" style={{ fontSize: 12 }}>
          {path}
        </span>
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
        <p className="muted">{file.error instanceof Error ? file.error.message : "This file can't be read."}</p>
      ) : file.data?.binary ? (
        <p className="muted">A binary file: not shown.</p>
      ) : file.data?.too_large ? (
        <p className="muted">Over 1 MB: not shown.</p>
      ) : file.data?.status === "deleted" ? (
        <p className="muted">The turn deleted this file.</p>
      ) : (
        <div className="kp-diff mono" role="table" aria-label={path}>
          {text.split("\n").map((l, i) => (
            <div key={i} className="kp-line ctx" role="row">
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
