// A coding session's details, as Claude Code's session column shows them: where Kai works (cloud sandbox or
// your computer, the repository and branch), the pull request with its checks, what the turns made (files and
// screenshots), what they used, and the tools and pinned skills Kai has. Flat sections, the most useful first;
// long text (why a tool is off, a skill's procedure) stays folded or one line, with the rest on hover.
// A column beside the session on wide screens (between it and any open panes); a popover on narrow ones.
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
        <span className="grow">{title}</span>
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
  const capabilities = latest?.capabilities ?? [];
  const skills = latest?.skills ?? [];
  const usable = capabilities.filter((capability) => capability.available).length;

  return (
    <div className="sd">
      <Section title="Environment">
        <div className="sd-env">
          <span className="sd-env-icon">
            <Ic n={local ? "monitor" : "cloud"} s={16} />
          </span>
          <span className="sd-env-text">
            <b>{local ? "Your computer" : "Cloud sandbox"}</b>
            <span className="faint trunc">{local ? (latest?.runner_name ?? "Waiting for a runner") : (SANDBOX[cs.sandbox ?? "none"] ?? cs.sandbox)}</span>
          </span>
          {!local && cs.sandbox && <span className={`sd-state ${cs.sandbox}`} aria-label={SANDBOX[cs.sandbox]} />}
        </div>
        <div className="sd-row">
          <Ic n="book-bookmark" s={14} />
          {repo ? (
            <a className="grow trunc" href={`https://github.com/${repo}`} target="_blank" rel="noreferrer">
              {repo}
            </a>
          ) : (
            <span className="grow faint">No repository connected to {cs.project_name}</span>
          )}
        </div>
        <div className="sd-row sd-branch">
          <Ic n="git-branch" s={14} />
          <span className="grow">
            {cs.branch ? <span className="mono">{cs.branch}</span> : <span className="faint">A new branch, made when the turn starts</span>}
            {latest?.base_branch && (
              <span className="faint">
                {" from "}
                <span className="mono">{latest.base_branch}</span>
                {latest.base_sha && <span className="mono"> @{latest.base_sha.slice(0, 7)}</span>}
              </span>
            )}
          </span>
        </div>
      </Section>

      <Section title="Pull request">
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
                <Ic n="shield-check" s={14} />
                <span className="grow">Juno's review on GitHub</span>
                <Ic n="arrow-up-right" s={13} />
              </a>
            )}
          </div>
        ) : files.length ? (
          <button className="sd-row sd-link" onClick={() => onOpenChanges()}>
            <Ic n="git-compare" s={14} />
            <span className="grow">Not pushed yet</span>
            <span className="plus">+{added}</span>
            <span className="minus">−{removed}</span>
          </button>
        ) : (
          <p className="sd-empty">Shows here once Kai pushes.</p>
        )}
      </Section>

      <Section title="Outputs" aside={files.length + shots.length > 0 ? <span className="sd-count">{files.length + shots.length}</span> : undefined}>
        {files.length === 0 && shots.length === 0 && <p className="sd-empty">Files Kai changes and screenshots it takes show here.</p>}
        {shown.map(([path, f]) => (
          <button key={path} className="sd-row sd-link" onClick={() => onOpenFile(path, f.turn)} title={path} aria-label={`Open ${path} in Files`}>
            <Ic n="file-code" s={14} />
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
            <Ic n="image" s={14} />
            <span className="grow trunc">{sh.name}</span>
          </button>
        ))}
      </Section>

      <Section title="Usage">
        <div className="sd-stats">
          <div className="sd-stat">
            <b>{num(tokens)}</b>
            <span>tokens</span>
          </div>
          <div className="sd-stat">
            <b>{cost ? `$${cost.toFixed(2)}` : "—"}</b>
            <span>on your key</span>
          </div>
          <div className="sd-stat">
            <b>{turns.length}</b>
            <span>turn{turns.length === 1 ? "" : "s"}</span>
          </div>
        </div>
        <div className="sd-row faint">
          <Ic n="sparkles" s={14} />
          <span className="grow trunc">
            {sessionModel(latest?.model)} · {modeName(latest?.approval_mode)}
          </span>
        </div>
      </Section>

      {capabilities.length > 0 && (
        <Section
          title="Tools and skills"
          aside={
            <span className="sd-count">
              {usable}/{capabilities.length} tools
            </span>
          }
        >
          <ul className="sd-tools">
            {capabilities.map((capability) => (
              <li key={capability.id} className={capability.available ? "on" : ""} title={capability.reason ?? undefined}>
                <span className="sd-tool">
                  <span className="sd-dot" aria-hidden="true" />
                  <span className="grow">{capability.label}</span>
                  <span className="sd-tool-state">{capability.available ? "Available" : "Unavailable"}</span>
                </span>
                {capability.reason && !capability.available && <span className="sd-why">{capability.reason}</span>}
              </li>
            ))}
          </ul>
          {skills.length > 0 && (
            <details className="sd-skills">
              <summary>
                <Ic n="chevron-right" s={13} />
                <span className="grow">Skills</span>
                <span className="sd-count">{skills.length}</span>
              </summary>
              {skills.map((skill) => (
                <details key={skill.name} className="sd-skill">
                  <summary>
                    <span className="grow trunc">{skill.name}</span>
                    {(skill.unavailable_tools.length > 0 || skill.missing_resources.length > 0) && (
                      <span className="sd-warn" title="Needs something this turn doesn't have">
                        <Ic n="triangle-alert" s={12} />
                      </span>
                    )}
                  </summary>
                  <p>{skill.description}</p>
                  {Boolean(skill.resources.length) && <p className="faint">Resources: {skill.resources.join(", ")}</p>}
                  {Boolean(skill.missing_resources.length) && <p className="sd-warn-text">Missing resources: {skill.missing_resources.join(", ")}</p>}
                  {Boolean(skill.unavailable_tools.length) && <p className="sd-warn-text">Unavailable required tools: {skill.unavailable_tools.join(", ")}</p>}
                  <p className="mono faint">Version {skill.sha256.slice(0, 12)}</p>
                </details>
              ))}
            </details>
          )}
        </Section>
      )}
    </div>
  );
}
