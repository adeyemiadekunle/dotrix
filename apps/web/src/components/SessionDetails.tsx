// A coding session's details popover: where Kai works (cloud sandbox or your computer, repository and
// branch), background tasks from the session's run/events API, pull request & checks, outputs, usage, and tools/skills.
import { useState, type ReactNode } from "react";
import { ActionButton } from "@dotrix/ui/components/action-button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@dotrix/ui/components/collapsible";

import { modelName } from "@/lib/agent";
import { statusLabel, useCodingEvents, type CodingRun, type CodingSession } from "@/lib/coding";
import type { Scope } from "@/lib/issues";
import { taskStatus } from "../core/backgroundTasks";
import { Ic } from "../core/icons";
import { toast } from "../ui/toast";
import { kaiBackground } from "./BackgroundTasks";

const fileOf = (f: Record<string, unknown>) => String(f.path ?? "");
const num = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n.toLocaleString());
const MODE: Record<string, string> = { manual: "Manual", accept_edits: "Accept edits", auto: "Auto" };
const SANDBOX: Record<string, string> = { warm: "Sandbox ready", asleep: "Sandbox asleep", none: "Starts a sandbox on the next turn" };
const BG_STATES: Record<string, string> = {
  running: "Running",
  done: "Done",
  failed: "Failed",
  stopped: "Stopped",
  ended: "Ended",
};

function Section({ title, children, aside, defaultOpen = true }: { title: string; children: ReactNode; aside?: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="sd-sec" data-open={open}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <h3>
          <CollapsibleTrigger className="sd-sec-toggle">
            <Ic n="chevron-right" s={12} cls="sd-sec-chev" />
            <span className="grow">{title}</span>
            {aside}
          </CollapsibleTrigger>
        </h3>
        <CollapsibleContent className="sd-sec-body">{children}</CollapsibleContent>
      </Collapsible>
    </section>
  );
}

/** The model a session's turns use, as people say it: "Sonnet 5.5". */
export const sessionModel = (model: string | null | undefined) => (model ? modelName(model) : "Your default model");
export const modeName = (mode: string | null | undefined) => MODE[mode ?? ""] ?? "Manual";

export function SessionDetails({
  scope,
  cs,
  turns,
  onOpenFile,
  onOpenChanges,
  onShot,
  shotSrc,
  onClose,
  onRefresh,
  refreshing = false,
}: {
  scope?: Scope;
  cs: CodingSession;
  turns: CodingRun[];
  onOpenFile: (path: string, turnId?: string) => void;
  onOpenChanges: (turnId?: string) => void;
  onShot: (src: string, name: string) => void;
  shotSrc: (runId: string, index: number) => string;
  onClose?: () => void;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  const [allFiles, setAllFiles] = useState(false);
  const latest = turns.at(-1);
  const local = (latest?.location ?? cs.location) === "local";
  const eventsQuery = useCodingEvents(scope, latest, Boolean(scope && latest));
  const latestEvents = eventsQuery.data ?? latest?.events ?? [];
  const bgWork = kaiBackground(latestEvents);
  const runTasks = latest?.tasks?.length ? latest.tasks : turns.flatMap((t) => t.tasks ?? []);
  const bgCount = runTasks.length + bgWork.length;
  const runStatus = latest?.status ?? cs.status;
  const bgRunning =
    runTasks.filter((t) => runStatus === "running" && ["running", "verifying"].includes(t.status)).length + bgWork.filter((w) => w.state === "running").length;

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
  const headerStatus = runStatus ? statusLabel({ status: runStatus, location: latest?.location ?? cs.location, runner_name: latest?.runner_name }) : null;

  const copyBranch = () => {
    if (!cs.branch) return;
    void navigator.clipboard
      ?.writeText(cs.branch)
      .then(() => toast("Branch copied"))
      .catch(() => toast("It couldn't be copied"));
  };

  return (
    <div className="sd">
      <div className="sd-head">
        <b>Session details</b>
        {headerStatus && <span className={`sd-pill ${runStatus === "running" ? "running" : ""}`}>{headerStatus}</span>}
        <span className="grow" />
        {onRefresh && (
          <ActionButton
            className="ibtn ibtn-xs"
            onClick={() => {
              onRefresh();
              if (scope && latest) void eventsQuery.refetch();
            }}
            disabled={refreshing || eventsQuery.isFetching}
            aria-label="Refresh session details"
            data-tip="Refresh"
          >
            <Ic n="refresh-cw" s={13} cls={refreshing || eventsQuery.isFetching ? "animate-spin" : undefined} />
          </ActionButton>
        )}
        {onClose && (
          <ActionButton className="ibtn ibtn-xs" onClick={onClose} aria-label="Close session details" data-tip="Close">
            <Ic n="x" s={13} />
          </ActionButton>
        )}
      </div>

      <Section title="Environment">
        <div className="sd-card">
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
            {cs.branch && (
              <button type="button" className="ibtn ibtn-xs" onClick={copyBranch} aria-label="Copy branch name" data-tip="Copy branch">
                <Ic n="copy" s={12} />
              </button>
            )}
          </div>
        </div>
      </Section>

      <Section
        title="Background tasks"
        aside={bgCount > 0 ? <span className={`sd-pill ${bgRunning ? "running" : ""}`}>{bgRunning ? `${bgRunning} running` : bgCount}</span> : undefined}
      >
        {eventsQuery.isLoading && bgCount === 0 ? (
          <p className="sd-empty">Loading background tasks…</p>
        ) : eventsQuery.isError && bgCount === 0 ? (
          <p className="sd-empty">
            Background tasks couldn't be loaded.{" "}
            <button type="button" className="sd-more" onClick={() => void eventsQuery.refetch()}>
              Try again
            </button>
          </p>
        ) : bgCount === 0 ? (
          <p className="sd-empty">No background tasks in this session.</p>
        ) : (
          <div className="sd-bg-list">
            {runTasks.map((task) => {
              const running = runStatus === "running" && ["running", "verifying"].includes(task.status);
              const label = taskStatus(task.status, runStatus ?? "queued");
              return (
                <div className="sd-bg-item" key={task.key}>
                  <Ic
                    n={running ? "spinner-gap" : task.status === "completed" ? "check-circle" : "flow-arrow"}
                    cls={running ? "animate-spin sd-bg-ic" : "sd-bg-ic"}
                    s={14}
                  />
                  <span className="sd-bg-main">
                    <b className="trunc">{task.key}</b>
                    <span className="sd-bg-meta">
                      {label}
                      {task.owned_paths?.length ? ` · ${task.owned_paths.length} paths` : ""}
                    </span>
                  </span>
                </div>
              );
            })}
            {bgWork.map((w) => (
              <div className="sd-bg-item" key={w.ref}>
                <Ic
                  n={w.state === "running" ? "spinner-gap" : w.state === "done" ? "check-circle" : w.state === "failed" ? "warning-circle" : "stop-circle"}
                  cls={w.state === "running" ? "animate-spin sd-bg-ic" : "sd-bg-ic"}
                  s={14}
                />
                <span className="sd-bg-main">
                  {w.kind === "command" ? <code className="mono trunc">{w.label}</code> : <b className="trunc">{w.label}</b>}
                  <span className="sd-bg-meta">
                    {w.kind === "worker" ? "Worker" : "Command"} · {BG_STATES[w.state] ?? w.state}
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Pull request">
        {cs.pr_number && cs.pr_url ? (
          <div className="sd-card sd-pr">
            <a className="sd-pr-title" href={cs.pr_url} target="_blank" rel="noreferrer">
              <Ic n={cs.pr_state === "merged" ? "git-merge" : "git-pull-request"} s={15} />
              <span className="trunc">{cs.title ?? cs.issue_title}</span>
            </a>
            <div className="sd-pr-meta">
              <span className="faint">#{cs.pr_number}</span>
              <button type="button" className="sd-lines" onClick={() => onOpenChanges(pushed?.id)} title="Open the changes">
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
          <button type="button" className="sd-row sd-link" onClick={() => onOpenChanges()}>
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
          <button
            type="button"
            key={path}
            className="sd-row sd-link"
            onClick={() => onOpenFile(path, f.turn)}
            title={path}
            aria-label={`Open ${path} in Files`}
          >
            <Ic n="file-code" s={14} />
            <span className="grow trunc">{path.split("/").pop()}</span>
            {(f.added > 0 || f.removed > 0) && (
              <span className="sd-file-delta">
                {f.added > 0 && <span className="plus">+{f.added}</span>}
                {f.removed > 0 && <span className="minus">−{f.removed}</span>}
              </span>
            )}
            <span className="sd-dir trunc">{path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : ""}</span>
          </button>
        ))}
        {files.length > 6 && (
          <button type="button" className="sd-more" onClick={() => setAllFiles(!allFiles)}>
            {allFiles ? "Show fewer" : `Show ${files.length - 6} more`}
          </button>
        )}
        {shots.map((sh) => (
          <button type="button" key={`${sh.turn}:${sh.index}`} className="sd-row sd-link" onClick={() => onShot(shotSrc(sh.turn, sh.index), sh.name)}>
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
