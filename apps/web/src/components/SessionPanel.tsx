// A coding session's side panels, beside its turns (like the Claude desktop app's): the terminal,
// the changes, the app's preview, the repo's files, and background tasks. Several can be open at once,
// stacked and resizable against each other; the open ones are `?pane=` (comma-separated).
import { Fragment, useRef, useState } from "react";

import { Ic } from "../core/icons";
import { D, mutate } from "../data/store";
import type { CodingSession } from "../data/types";
import { Splitter } from "../ui/splitter";

export type Pane = "terminal" | "changes" | "browser" | "files" | "tasks";

export const PANES: [Pane, string, string][] = [
  ["terminal", "square-terminal", "Terminal"],
  ["changes", "file-diff", "Changes"],
  ["browser", "globe", "Browser"],
  ["files", "folder", "Files"],
  ["tasks", "list-checks", "Background tasks"],
];

const isPane = (v: string): v is Pane => PANES.some(([p]) => p === v);
/** The open panels from `?pane=`, in the order they were opened, at most three. */
export const panesOf = (v: string | null): Pane[] => [...new Set((v ?? "").split(",").filter(isPane))].slice(0, 3);
const meta = (p: Pane) => PANES.find(([x]) => x === p)!;

/** The panels' icons, top right: in the right column's head while panels are open, at the end of
 * the session's header when none are. Each opens its panel below the others, or closes it. */
export function PaneToolbar({ cs, panes, onToggle }: { cs: CodingSession; panes: Pane[]; onToggle: (p: Pane) => void }) {
  return (
    <div className="row cs-panes" role="toolbar" aria-label="Session panels">
      {PANES.map(([p, icon, name]) => (
        <button key={p} className={`ibtn ibtn-sm ${panes.includes(p) ? "on" : ""}`} onClick={() => onToggle(p)} aria-label={name} aria-pressed={panes.includes(p)} data-tip={name}>
          <Ic n={icon} s={15} />
          {p === "tasks" && (cs.tasks ?? []).some((x) => x.status === "running") && <span className="cs-live" aria-hidden />}
        </button>
      ))}
    </div>
  );
}

/** Opens a panel below the others (three at most), or closes it. */
export const togglePane = (panes: Pane[], p: Pane): Pane[] => (panes.includes(p) ? panes.filter((x) => x !== p) : [...panes, p].slice(-3));

/** The open panels, stacked; the handle between two moves the space between them. */
export function SessionPanels({ cs, panes, onPanes }: { cs: CodingSession; panes: Pane[]; onPanes: (p: Pane[]) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [weights, setWeights] = useState<Partial<Record<Pane, number>>>({});
  const resize = (i: number, delta: number) => {
    const a = panes[i]!;
    const b = panes[i + 1]!;
    const height = ref.current?.clientHeight || 600;
    setWeights((prev) => {
      const total = panes.reduce((n, p) => n + (prev[p] ?? 1), 0);
      const step = (delta / height) * total;
      const wa = (prev[a] ?? 1) + step;
      const wb = (prev[b] ?? 1) - step;
      const min = total * 0.12;
      return wa < min || wb < min ? prev : { ...prev, [a]: wa, [b]: wb };
    });
  };
  const open = (p: Pane) => onPanes(panes.includes(p) ? panes : [...panes, p].slice(-3));
  return (
    <div ref={ref} className="cs-stack">
      {panes.map((p, i) => (
        <Fragment key={p}>
          {i > 0 && <Splitter dir="row" label={`Resize ${meta(panes[i - 1]!)[2]} and ${meta(p)[2]}`} onDrag={(d) => resize(i - 1, d)} />}
          <section className="cs-panel" style={{ flex: `${weights[p] ?? 1} 1 0` }} aria-label={meta(p)[2]}>
            <div className="row cs-panel-h">
              <Ic n={meta(p)[1]} s={14} />
              <b className="trunc" style={{ fontSize: 12.5, fontWeight: 600 }}>
                {meta(p)[2]}
              </b>
              <span className="sp" />
              <button className="ibtn ibtn-sm" onClick={() => onPanes(panes.filter((x) => x !== p))} aria-label={`Close ${meta(p)[2]}`}>
                <Ic n="x" s={15} />
              </button>
            </div>
            <div className="cs-panel-b">
              {p === "terminal" && <Terminal cs={cs} />}
              {p === "changes" && <Changes cs={cs} />}
              {p === "browser" && <Browser cs={cs} onOpen={open} />}
              {p === "files" && <Files cs={cs} />}
              {p === "tasks" && <Tasks cs={cs} />}
            </div>
          </section>
        </Fragment>
      ))}
    </div>
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
function Browser({ cs, onOpen }: { cs: CodingSession; onOpen: (p: Pane) => void }) {
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
          <button className="linkbtn" onClick={() => onOpen("tasks")}>
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
