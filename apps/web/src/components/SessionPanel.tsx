// A coding session's side panel, beside its turns (like the Claude desktop app's): the terminal,
// the changes, the app's preview, the repo's files, and background tasks. The open tab is `?pane=`.
import { useState } from "react";

import { Ic } from "../core/icons";
import { D, mutate } from "../data/store";
import type { CodingSession } from "../data/types";

export type Pane = "terminal" | "changes" | "browser" | "files" | "tasks";

export const PANES: [Pane, string, string][] = [
  ["terminal", "square-terminal", "Terminal"],
  ["changes", "file-diff", "Changes"],
  ["browser", "globe", "Browser"],
  ["files", "folder", "Files"],
  ["tasks", "list-checks", "Background tasks"],
];

const isPane = (v: string | null): v is Pane => PANES.some(([p]) => p === v);
export const paneOf = (v: string | null): Pane | null => (isPane(v) ? v : null);

export function SessionPanel({ cs, pane, onPane }: { cs: CodingSession; pane: Pane; onPane: (p: Pane | null) => void }) {
  const name = PANES.find(([p]) => p === pane)?.[2];
  return (
    <aside className="cs-panel" aria-label={name}>
      <div className="row cs-panel-h">
        <Ic n={PANES.find(([p]) => p === pane)?.[1] ?? "panel-right"} s={14} />
        <b className="trunc" style={{ fontSize: 12.5, fontWeight: 600 }}>
          {name}
        </b>
        <span className="sp" />
        <button className="ibtn ibtn-sm" onClick={() => onPane(null)} aria-label="Close the panel">
          <Ic n="x" s={15} />
        </button>
      </div>
      <div className="cs-panel-b">
        {pane === "terminal" && <Terminal cs={cs} />}
        {pane === "changes" && <Changes cs={cs} />}
        {pane === "browser" && <Browser cs={cs} onPane={onPane} />}
        {pane === "files" && <Files cs={cs} />}
        {pane === "tasks" && <Tasks cs={cs} />}
      </div>
    </aside>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <div className="faint cs-note">{children}</div>;
}

/** What the agent ran in the sandbox, with what it printed. Read-only. */
function Terminal({ cs }: { cs: CodingSession }) {
  const lines = cs.terminal ?? [];
  return (
    <>
      <div className="cs-term" role="log" aria-label="What the agent ran">
        {lines.length ? (
          lines.map((l, i) => (
            <div key={i}>
              <div>
                <span className="cs-prompt">sandbox:~/repo$</span> {l.cmd}
              </div>
              {l.out && <pre>{l.out}</pre>}
            </div>
          ))
        ) : (
          <div className="faint">Nothing has run yet.</div>
        )}
        {cs.status === "running" && <span className="cs-cursor" aria-hidden />}
      </div>
      <Note>Read-only: what the agent ran in its sandbox. Typing here comes later, under the session's approval mode.</Note>
    </>
  );
}

/** The branch against its base, a diff per file. */
function Changes({ cs }: { cs: CodingSession }) {
  const files = cs.files ?? [];
  const [open, setOpen] = useState<Record<string, boolean>>(() => Object.fromEntries(files.slice(0, 2).map((f) => [f.path, true])));
  if (!files.length) return <Note>No changes yet. They show here when a turn ends, from its commit.</Note>;
  return (
    <>
      <div className="row cs-branch mono">
        <span className="faint">{cs.base?.branch ?? "main"}</span>
        <Ic n="arrow-right" s={12} />
        <span className="trunc">{cs.branch ?? "a new branch"}</span>
      </div>
      {files.map((f) => {
        const diff = cs.diffs?.[f.path];
        const on = open[f.path];
        return (
          <section key={f.path} className="cs-dfile">
            <button className="row cs-dfile-h" onClick={() => setOpen({ ...open, [f.path]: !on })} aria-expanded={on}>
              <Ic n={on ? "chevron-down" : "chevron-right"} s={13} />
              <span className="mono trunc grow" style={{ textAlign: "left" }}>
                {f.path}
              </span>
              <span className="cs-add">+{f.added}</span>
              <span className="cs-del">−{f.removed}</span>
            </button>
            {on &&
              (diff ? (
                <pre className="cs-diff">
                  {diff.split("\n").map((line, i) => (
                    <span key={i} className={line.startsWith("+") ? "a" : line.startsWith("-") ? "d" : line.startsWith("@@") ? "h" : ""}>
                      {line || " "}
                      {"\n"}
                    </span>
                  ))}
                </pre>
              ) : (
                <Note>The diff comes from the turn's commit once the session is wired to the API.</Note>
              ))}
          </section>
        );
      })}
    </>
  );
}

/** The app as the sandbox serves it: a dev server the supervisor started, through the platform. */
function Browser({ cs, onPane }: { cs: CodingSession; onPane: (p: Pane) => void }) {
  const server = (cs.tasks ?? []).find((t) => t.port && t.status === "running");
  const [path, setPath] = useState(cs.preview?.path ?? "/");
  return (
    <>
      <div className="row cs-url">
        <Ic n="lock" s={12} />
        <input className="mono" value={server ? `preview · :${server.port}${path}` : "No app running"} readOnly={!server} onChange={(e) => setPath(e.target.value.replace(/^preview · :\d+/, "") || "/")} aria-label="Address" />
        <button className="ibtn ibtn-xs" aria-label="Reload" disabled={!server}>
          <Ic n="rotate-cw" s={13} />
        </button>
      </div>
      {server ? (
        <div className="cs-preview" role="img" aria-label="The app's preview">
          <div className="cs-preview-bar" />
          <div className="cs-preview-hero" />
          <div className="cs-preview-row">
            <i />
            <i />
            <i />
          </div>
          <span className="faint">
            {server.name} on :{server.port}, served through the platform (never an open port)
          </span>
        </div>
      ) : (
        <Note>
          The agent's app shows here once a dev server runs in the sandbox.{" "}
          <button className="linkbtn" onClick={() => onPane("tasks")}>
            Background tasks
          </button>{" "}
          start and stop it.
        </Note>
      )}
    </>
  );
}

/** The repo's tracked files, changed ones marked. */
function Files({ cs }: { cs: CodingSession }) {
  const changed = new Map((cs.files ?? []).map((f) => [f.path, f.status ?? "modified"]));
  const paths = [...new Set([...(cs.tree ?? []), ...changed.keys()])].sort();
  if (!paths.length) return <Note>The file tree shows once the sandbox has the repo.</Note>;
  // Folders first in each level, from the flat list of paths.
  type Node = { name: string; path: string; kids: Map<string, Node>; file: boolean };
  const root: Node = { name: "", path: "", kids: new Map(), file: false };
  for (const p of paths) {
    let at = root;
    p.split("/").forEach((part, i, all) => {
      const path = all.slice(0, i + 1).join("/");
      if (!at.kids.has(part)) at.kids.set(part, { name: part, path, kids: new Map(), file: i === all.length - 1 });
      at = at.kids.get(part)!;
    });
  }
  const render = (n: Node, depth: number): React.ReactNode =>
    [...n.kids.values()]
      .sort((a, b) => Number(a.file) - Number(b.file) || a.name.localeCompare(b.name))
      .map((k) => (
        <div key={k.path}>
          <div className="row cs-fnode" style={{ paddingLeft: 10 + depth * 14 }}>
            <Ic n={k.file ? "file" : "folder"} s={13} />
            <span className={`mono trunc grow ${changed.has(k.path) ? "cs-fchanged" : ""}`}>{k.name}</span>
            {changed.has(k.path) && <span className={`cs-st ${changed.get(k.path)}`}>{changed.get(k.path) === "added" ? "A" : changed.get(k.path) === "deleted" ? "D" : "M"}</span>}
          </div>
          {!k.file && render(k, depth + 1)}
        </div>
      ));
  return <div className="cs-files">{render(root, 0)}</div>;
}

/** Long-running commands the supervisor runs in the sandbox (dev servers, watchers, test runs). */
function Tasks({ cs }: { cs: CodingSession }) {
  const tasks = cs.tasks ?? [];
  const stop = (id: string) =>
    mutate(() => {
      const t = D().coding.find((x) => x.id === cs.id)?.tasks?.find((x) => x.id === id);
      if (t) t.status = "stopped";
    });
  if (!tasks.length) return <Note>No background tasks. Dev servers and watchers the agent starts show here, run by the platform's supervisor.</Note>;
  return (
    <>
      {tasks.map((t) => (
        <div key={t.id} className="row cs-task">
          <span className={`cs-dot ${t.status}`} aria-hidden />
          <div className="grow" style={{ minWidth: 0 }}>
            <div className="row" style={{ gap: 6 }}>
              <b style={{ fontWeight: 500 }}>{t.name}</b>
              {t.port && <span className="badge">:{t.port}</span>}
              <span className="faint" style={{ fontSize: 11.5 }}>
                {t.status}
              </span>
            </div>
            <div className="mono faint trunc" style={{ fontSize: 11.5 }}>
              {t.cmd}
            </div>
          </div>
          {t.status === "running" && (
            <button className="btn btn-sm btn-ghost" onClick={() => stop(t.id)}>
              <Ic n="square" s={12} />
              Stop
            </button>
          )}
        </div>
      ))}
      <Note>Run by the platform's supervisor, not the agent, so they outlive a turn; they stop when the sandbox goes idle.</Note>
    </>
  );
}
