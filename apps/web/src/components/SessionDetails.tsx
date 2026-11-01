// A coding session's details, as Claude Code's session column shows them: where Kai works (cloud sandbox or
// your computer, the repository and branch), what the turns used, what they made (files and screenshots), and
// the pull request with its checks. A column beside the session on wide screens; a popover on narrow ones.
import { useState, type ReactNode } from "react";

import { modelName } from "@/lib/agent";
import type { CodingRun, CodingSession } from "@/lib/coding";
import { Ic } from "../core/icons";

const fileOf = (f: Record<string, unknown>) => String(f.path ?? "");
const num = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n.toLocaleString());
const MODE: Record<string, string> = { manual: "Manual", accept_edits: "Accept edits", auto: "Auto" };
const SANDBOX: Record<string, string> = { warm: "Sandbox ready", asleep: "Sandbox asleep", none: "Starts a sandbox on the next turn" };

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="sd-sec">
      <h3>
        {title}
        {aside}
      </h3>
      {children}
    </section>
  );
}

/** The model a session's turns use, as people say it: "Sonnet 5.5". */
export const sessionModel = (model: string | null | undefined) => (model ? modelName(model) : "Your default model");
export const modeName = (mode: string | null | undefined) => MODE[mode ?? ""] ?? "Manual";

export function SessionDetails({
  cs,
  turns,
  onOpenFile,
  onOpenChanges,
  onShot,
  shotSrc,
}: {
  cs: CodingSession;
  turns: CodingRun[];
  onOpenFile: (path: string, turnId?: string) => void;
  onOpenChanges: (turnId?: string) => void;
  onShot: (src: string, name: string) => void;
  shotSrc: (runId: string, index: number) => string;
}) {
  const [allFiles, setAllFiles] = useState(false);
  const latest = turns.at(-1);
  const local = (latest?.location ?? cs.location) === "local";
  // Every file the session changed, with the latest turn that changed it, newest first.
  const outputs = new Map<string, { turn: string; added: number; removed: number }>();
  for (const turn of [...turns].reverse())
    for (const f of turn.files_changed)
      if (!outputs.has(fileOf(f))) outputs.set(fileOf(f), { turn: turn.id, added: Number(f.added ?? 0), removed: Number(f.removed ?? 0) });
  const files = [...outputs.entries()];
  const shots = turns.flatMap((turn) => (turn.screenshots ?? []).map((sh) => ({ turn: turn.id, ...sh })));
  const tokens = turns.reduce((n, t) => n + (t.input_tokens ?? 0) + (t.output_tokens ?? 0), 0);
  const cost = turns.reduce((n, t) => n + (t.cost_usd ?? 0), 0);
  const added = files.reduce((n, [, f]) => n + f.added, 0);
  const removed = files.reduce((n, [, f]) => n + f.removed, 0);
  const pushed = [...turns].reverse().find((t) => t.commit_sha && t.pr_number);
  const repo = latest?.repo_full_name;
  const shown = allFiles ? files : files.slice(0, 6);

  return (
    <div className="sd">
      <Section title="Environment">
        <div className="sd-row">
          <Ic n={local ? "monitor" : "cloud"} s={15} />
          <span className="grow">{local ? `Your computer${latest?.runner_name ? ` · ${latest.runner_name}` : ""}` : "Cloud"}</span>
          {!local && cs.sandbox && <span className={`sd-state ${cs.sandbox}`} title={SANDBOX[cs.sandbox] ?? cs.sandbox} aria-label={SANDBOX[cs.sandbox]} />}
        </div>
        <div className="sd-row">
          <Ic n="book-bookmark" s={15} />
          {repo ? (
            <a className="grow trunc" href={`https://github.com/${repo}`} target="_blank" rel="noreferrer">
              {repo}
            </a>
          ) : (
            <span className="grow faint">No repository connected to {cs.project_name}</span>
          )}
        </div>
        <div
          className="sd-row"
          title={latest?.base_branch ? `From ${latest.base_branch}${latest.base_sha ? `@${latest.base_sha.slice(0, 7)}` : ""}` : undefined}
        >
          <Ic n="git-branch" s={15} />
          <span className="grow trunc mono">{cs.branch ?? <span className="faint">A new branch, made when it starts</span>}</span>
        </div>
      </Section>

      <Section title="Usage">
        <div className="sd-usage">
          <span>
            <b>{num(tokens)}</b> tokens
          </span>
          <span>
            <b>{cost ? `$${cost.toFixed(2)}` : "—"}</b> on your key
          </span>
          <span>
            <b>{turns.length}</b> turn{turns.length === 1 ? "" : "s"}
          </span>
        </div>
        <div className="sd-row faint">
          <Ic n="sparkles" s={15} />
          <span className="grow trunc">
            {sessionModel(latest?.model)} · {modeName(latest?.approval_mode)}
          </span>
        </div>
      </Section>

      <Section title="Outputs" aside={files.length > 0 ? <span className="sd-count">{files.length}</span> : undefined}>
        {files.length === 0 && shots.length === 0 && <p className="faint sd-empty">Files Kai changes and screenshots it takes show here.</p>}
        {shown.map(([path, f]) => (
          <button key={path} className="sd-row sd-link" onClick={() => onOpenFile(path, f.turn)} title={path} aria-label={`Open ${path} in Files`}>
            <Ic n="file-code" s={15} />
            <span className="grow trunc">{path.split("/").pop()}</span>
            <span className="sd-dir trunc">{path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : ""}</span>
          </button>
        ))}
        {files.length > 6 && (
          <button className="sd-more" onClick={() => setAllFiles(!allFiles)}>
            {allFiles ? "Show fewer" : `Show ${files.length - 6} more`}
          </button>
        )}
        {shots.map((sh) => (
          <button key={`${sh.turn}:${sh.index}`} className="sd-row sd-link" onClick={() => onShot(shotSrc(sh.turn, sh.index), sh.name)}>
            <Ic n="image" s={15} />
            <span className="grow trunc">{sh.name}</span>
          </button>
        ))}
      </Section>

      <Section title="Changes">
        {cs.pr_number && cs.pr_url ? (
          <div className="sd-pr">
            <a className="sd-pr-title" href={cs.pr_url} target="_blank" rel="noreferrer">
              <Ic n={cs.pr_state === "merged" ? "git-merge" : "git-pull-request"} s={15} />
              <span className="trunc">{cs.title ?? cs.issue_title}</span>
            </a>
            <div className="sd-pr-meta">
              <span className="faint">#{cs.pr_number}</span>
              <button className="sd-lines" onClick={() => onOpenChanges(pushed?.id)} title="Open the changes">
                <span className="plus">+{added.toLocaleString()}</span>
                <span className="minus">−{removed.toLocaleString()}</span>
              </button>
              <span className="grow" />
              {pushed?.ci_state ? (
                <span className={`sd-ci ${pushed.ci_state}`}>
                  <Ic n={pushed.ci_state === "passed" ? "circle-check" : "circle-x"} s={13} />
                  CI {pushed.ci_state}
                </span>
              ) : (
                <span className="sd-ci">
                  <Ic n="circle-dashed" s={13} />
                  Checks pending
                </span>
              )}
            </div>
            {pushed?.review_posted_url && (
              <a className="sd-row sd-link" href={pushed.review_posted_url} target="_blank" rel="noreferrer">
                <Ic n="shield-check" s={15} />
                <span className="grow">Juno's review on GitHub</span>
                <Ic n="arrow-up-right" s={13} />
              </a>
            )}
          </div>
        ) : files.length ? (
          <button className="sd-row sd-link" onClick={() => onOpenChanges()}>
            <Ic n="git-compare" s={15} />
            <span className="grow">No pull request yet</span>
            <span className="plus">+{added}</span>
            <span className="minus">−{removed}</span>
          </button>
        ) : (
          <p className="faint sd-empty">The pull request shows here once Kai pushes.</p>
        )}
      </Section>
    </div>
  );
}
