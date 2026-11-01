// The right side panel beside one of Kai's sessions in Codes, resizable by its left edge.
// It shows one of the selected turn's Changes, Files, Terminal, or Juno's Review, picked by the buttons in the
// session header (as Claude Code's title bar opens its panes); Juno's findings also show on their lines in Changes.
// A turn picker and a close button in its header; on narrow screens the panel floats over the page.
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { Run } from "@/lib/agent";
import { api, unwrap } from "@/lib/api";
import { useCodingDiff, useCodingSession, type CodingRun, type CodingSession } from "@/lib/coding";
import { useCreateIssue, type Scope } from "@/lib/issues";
import { useReviewRunQueries } from "@/lib/team";
import { Markdown } from "@/components/markdown";
import { createTask, openTask } from "../core/actions";
import { allowed } from "../core/can";
import { Ic } from "../core/icons";
import { parseDiff } from "../core/kaiWork";
import { go, useRoute } from "../core/nav";
import { isLive, live } from "../data/live";
import { me } from "../data/store";
import { Splitter, useStoredSize } from "../ui/splitter";
import { tabKeys } from "../ui/tabs";
import { toast } from "../ui/toast";
import { ChangesView, FilesView, TerminalView, type DiffNote } from "./TurnViews";

const text = (value: unknown) => (typeof value === "string" ? value : "");
const narrowPanel = () => window.matchMedia("(max-width: 1200px)").matches;

/** The panel's frame: the drag edge, a one-line header (what it shows, the turn, close), and the body.
 *  Stacked (Codes' panes, several at once in one column), it has no edge of its own: the column has it. */
function PanelFrame({
  label,
  widthKey,
  title,
  tools,
  onClose,
  closeLabel = "Close the panel",
  stacked = false,
  expanded = false,
  onExpand,
  children,
}: {
  label: string;
  widthKey: string;
  title: ReactNode;
  tools?: ReactNode;
  onClose: () => void;
  closeLabel?: string;
  stacked?: boolean;
  expanded?: boolean;
  onExpand?: () => void;
  children: ReactNode;
}) {
  const [width, setWidth] = useStoredSize(widthKey, 460, 300, 960);
  const closeButton = useRef<HTMLButtonElement>(null);
  // Floating over the page on narrow screens: focus moves in, and Escape closes it.
  useEffect(() => {
    if (stacked || !narrowPanel()) return;
    const previous = document.activeElement;
    closeButton.current?.focus();
    return () => {
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, [stacked]);
  useEffect(() => {
    if (stacked) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && narrowPanel()) onClose();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose, stacked]);
  const head = (
    <div className="side-panel-head">
      {title}
      <span className="sp" />
      {tools}
      {onExpand && (
        <button
          className="ibtn ibtn-sm"
          onClick={onExpand}
          aria-label={expanded ? `Show the other panes` : `Expand ${label}`}
          data-tip={expanded ? "Restore" : "Expand"}
        >
          <Ic n={expanded ? "arrows-in" : "arrows-out"} s={14} />
        </button>
      )}
      <button ref={closeButton} className="ibtn ibtn-sm" onClick={onClose} aria-label={closeLabel} data-tip="Close">
        <Ic n="x" s={14} />
      </button>
    </div>
  );
  if (stacked)
    return (
      <section className="pane" aria-label={label}>
        {head}
        {children}
      </section>
    );
  return (
    <aside className="side-panel" style={{ width }} aria-label={label}>
      <Splitter dir="col" className="side-panel-split" label="Resize the panel" onDrag={(delta) => setWidth((w) => w - delta)} />
      {head}
      {children}
    </aside>
  );
}

/** Codes' panes: the views a session has open (Changes, Files, Terminal, Review), stacked in one resizable
 *  column, as Claude Code stacks its panes; one can be expanded to the whole column. */
export function CodingPanes({
  scope,
  cs,
  views,
  onOpen,
  onClose,
  onCloseAll,
  onAskFix,
  fixLabel,
}: {
  scope: Scope | undefined;
  cs: CodingSession;
  views: CodingView[];
  onOpen: (view: CodingView, extra?: Record<string, string>) => void;
  onClose: (view: CodingView) => void;
  onCloseAll: () => void;
  onAskFix?: (message: string) => void;
  fixLabel: string;
}) {
  const [width, setWidth] = useStoredSize("dotrix.coding.panes.width", 560, 320, 1100);
  const [expanded, setExpanded] = useState<CodingView | null>(null);
  const shown = expanded && views.includes(expanded) ? [expanded] : views;
  // Over the page on narrow screens: Escape closes the panes.
  const closeAll = useRef(onCloseAll);
  closeAll.current = onCloseAll;
  const column = useRef<HTMLElement>(null);
  // Over the page on narrow screens: focus moves into the panes, and back to where it was when they close.
  useEffect(() => {
    if (!narrowPanel()) return;
    const previous = document.activeElement;
    column.current?.querySelector<HTMLButtonElement>('button[aria-label^="Close"]')?.focus();
    return () => {
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && narrowPanel()) closeAll.current();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);
  return (
    <aside ref={column} className="side-panel panes" style={{ width }} aria-label="Session panes">
      <Splitter dir="col" className="side-panel-split" label="Resize the panes" onDrag={(delta) => setWidth((w) => w - delta)} />
      {shown.map((view) => (
        <CodingPanel
          key={view}
          scope={scope}
          cs={cs}
          view={view}
          onView={(next, extra) => onOpen(next, extra)}
          onClose={() => {
            if (expanded === view) setExpanded(null);
            onClose(view);
          }}
          onAskFix={onAskFix}
          onCloseAll={onCloseAll}
          fixLabel={fixLabel}
          stacked
          expanded={expanded === view}
          onExpand={views.length > 1 ? () => setExpanded(expanded === view ? null : view) : undefined}
        />
      ))}
    </aside>
  );
}

/** A session's turns and the one picked (the latest unless one is chosen), with its parsed diff. */
function useTurn(scope: Scope | undefined, cs: CodingSession | null | undefined, initial: string | null) {
  const [picked, setPicked] = useState<string | null>(initial);
  const turnsQuery = useCodingSession(scope, cs?.session_id);
  const turns = turnsQuery.data ?? [];
  const turn = turns.find((candidate) => candidate.id === picked) ?? turns.at(-1);
  const diff = useCodingDiff(scope, turn);
  const files = useMemo(() => parseDiff(diff.data?.diff ?? ""), [diff.data?.diff]);
  return { turnsQuery, turns, turn, setPicked, diff, files };
}

function TurnPicker({ turns, turn, onPick }: { turns: CodingRun[]; turn: CodingRun | undefined; onPick: (id: string) => void }) {
  if (!turn) return null;
  if (turns.length === 1) return <span className="side-panel-turn">Turn {turn.turn}</span>;
  return (
    <select className="input input-sm side-panel-select" value={turn.id} aria-label="Turn" onChange={(event) => onPick(event.target.value)}>
      {turns.map((candidate) => (
        <option key={candidate.id} value={candidate.id}>
          Turn {candidate.turn}
        </option>
      ))}
    </select>
  );
}

function NoTurn({ query }: { query: ReturnType<typeof useCodingSession> }) {
  return (
    <p className="muted">
      {query.isLoading ? "Loading the coding turn…" : query.isError ? "The coding turns couldn't be loaded." : "No coding turns yet."}
      {query.isError && (
        <button className="btn btn-sm btn-ghost" onClick={() => void query.refetch()}>
          Try again
        </button>
      )}
    </p>
  );
}

/** What Coding's panel shows; the session header's buttons pick it (screens/Chat.tsx Session). */
export type CodingView = "changes" | "files" | "terminal" | "review";
export const CODING_VIEWS: { id: CodingView; label: string; icon: string }[] = [
  { id: "changes", label: "Changes", icon: "git-compare" },
  { id: "files", label: "Files", icon: "folder-tree" },
  { id: "terminal", label: "Terminal", icon: "square-terminal" },
  { id: "review", label: "Review", icon: "shield-check" },
];

/** Juno's findings with a `path:line` reference, by path: shown on those lines in Changes. */
function findingNotes(review: Run | undefined, turn: CodingRun | undefined): Map<string, DiffNote[]> {
  const notes = new Map<string, DiffNote[]>();
  if (!review || !turn || text(review.review_context?.coding_run_id) !== turn.id) return notes;
  for (const output of review.outputs ?? []) {
    if (output.kind !== "finding") continue;
    for (const item of output.items) {
      const finding = item.data as Record<string, unknown>;
      for (const ref of Array.isArray(finding.refs) ? finding.refs : []) {
        const match = text(ref).match(/^(.*?):(\d+)(?:[-:]\d+)?$/);
        if (!match) continue;
        const list = notes.get(match[1]!) ?? [];
        list.push({ line: Number(match[2]), title: text(finding.title) || "Finding", severity: text(finding.severity) });
        notes.set(match[1]!, list);
      }
    }
  }
  return notes;
}

/** Coding: one view of a session's turn at a time (Changes, Files, Terminal, Review), picked from the session header. */
function CodingPanel({
  scope,
  cs,
  view,
  onView,
  onClose,
  onAskFix,
  fixLabel,
  stacked = false,
  expanded = false,
  onExpand,
  onCloseAll,
}: {
  scope: Scope | undefined;
  cs: CodingSession;
  view: CodingView;
  onView: (view: CodingView, extra?: Record<string, string>) => void;
  onClose: () => void;
  onAskFix?: (message: string) => void;
  fixLabel: string;
  stacked?: boolean;
  expanded?: boolean;
  onExpand?: () => void;
  onCloseAll?: () => void;
}) {
  const query = useRoute().search;
  const queryTurn = query.get("turn");
  const { turnsQuery, turns, turn, setPicked, diff, files } = useTurn(scope, cs, queryTurn);
  // A link that names a turn (a file path in the transcript, a review reference) picks it.
  useEffect(() => {
    if (queryTurn) setPicked(queryTurn);
  }, [queryTurn, setPicked]);
  const [selectedReview, setSelectedReview] = useState<string | null>(null);
  const [reference, setReference] = useState<{ turn: string; path: string; line?: number; version: number } | null>(null);
  const latestChanged = [...turns].reverse().find((turn) => turn.files_changed.length && ["pr_opened", "changes_ready"].includes(turn.status));
  const reviewQueries = useReviewRunQueries(
    scope,
    turns.flatMap((turn) => (turn.review_run_id ? [turn.review_run_id] : [])),
  );
  const reviews = reviewQueries.flatMap((result) => (result.data ? [result.data] : [])).sort((a, b) => b.created_at.localeCompare(a.created_at));
  const review = selectedReview
    ? reviews.find((candidate) => candidate.id === selectedReview)
    : turn?.review_run_id
      ? reviews.find((candidate) => candidate.id === turn.review_run_id)
      : (reviews.find((candidate) => turn && text(candidate.review_context?.coding_run_id) === turn.id) ?? reviews[0]);
  const turnReview = turn?.review_run_id ? reviews.find((candidate) => candidate.id === turn.review_run_id) : undefined;
  const notes = useMemo(() => findingNotes(turnReview, turn), [turnReview, turn]);
  const initialFile =
    reference && reference.turn === turn?.id ? reference.path : !queryTurn || queryTurn === turn?.id ? (query.get("file") ?? undefined) : undefined;
  const lineFromQuery = Number(query.get("line"));
  const initialLine =
    reference && reference.turn === turn?.id ? reference.line : initialFile && Number.isInteger(lineFromQuery) && lineFromQuery > 0 ? lineFromQuery : undefined;

  const openReference = (ref: string, review: Run) => {
    const match = ref.match(/^(.*?):(\d+)(?:[-:]\d+)?$/);
    const path = match ? match[1]! : ref;
    const line = match ? Number(match[2]) : undefined;
    const turn = text(review.review_context?.coding_run_id),
      session = text(review.review_context?.session_id);
    if (!turn || !session || !path || path.startsWith("/") || path.includes("..")) return;
    if (cs.session_id === session && stacked) {
      // Stacked panes each keep their own state: the reference goes to Files through the address
      // (`ref` changes each time, so the same line opens again after going back to the files).
      onView("files", { turn, file: path, ...(line ? { line: String(line) } : {}), ref: String(Date.now()) });
    } else if (cs.session_id === session) {
      setPicked(turn);
      setReference((previous) => ({ turn, path, line, version: (previous?.version ?? 0) + 1 }));
      onView("files");
    } else {
      const search = new URLSearchParams({ session, turn, file: path, panel: "files" });
      if (line) search.set("line", String(line));
      go("codes", {}, { search: search.toString() });
    }
  };
  const current = CODING_VIEWS.find((item) => item.id === view)!;
  return (
    <PanelFrame
      label={current.label}
      widthKey="dotrix.coding.panel.width"
      onClose={onClose}
      closeLabel={`Close ${current.label}`}
      stacked={stacked}
      expanded={expanded}
      onExpand={onExpand}
      title={
        <span className="side-panel-title">
          <Ic n={current.icon} s={14} />
          {view === "changes" && turn?.base_branch ? (
            // Where the turn's changes go, as Claude Code's diff header says it: base → branch.
            <b className="mono side-panel-branch" title={`${turn.base_branch} → ${turn.branch ?? cs.branch ?? "a new branch"}`}>
              {turn.base_branch} <span className="faint">→</span> {turn.branch ?? cs.branch ?? "new branch"}
            </b>
          ) : (
            <b>{current.label}</b>
          )}
          {view === "terminal" && <span className="faint">Recorded output · read-only</span>}
        </span>
      }
      tools={
        <TurnPicker
          turns={turns}
          turn={turn}
          onPick={(picked) => {
            setPicked(picked);
            setReference(null);
            setSelectedReview(null);
          }}
        />
      }
    >
      <div className="side-panel-body">
        {view === "review" ? (
          <ReviewPanel
            scope={scope}
            reviews={reviews}
            run={review}
            onSelectReview={setSelectedReview}
            latestTurn={latestChanged?.id}
            sessionId={cs.session_id}
            loading={reviewQueries.some((result) => result.isLoading)}
            failed={reviewQueries.some((result) => result.isError)}
            onRetry={() => reviewQueries.filter((result) => result.isError).forEach((result) => void result.refetch())}
            onAskFix={
              onAskFix
                ? (message) => {
                    onAskFix(message);
                    if (narrowPanel()) (onCloseAll ?? onClose)();
                  }
                : undefined
            }
            fixLabel={fixLabel}
            onReference={openReference}
          />
        ) : !turn ? (
          <NoTurn query={turnsQuery} />
        ) : (
          // All three stay mounted while the panel is open, so a file opened in Files is still open on the way back.
          <>
            <div hidden={view !== "changes"}>
              <ChangesView
                run={turn}
                files={files}
                loading={diff.isLoading}
                error={diff.isError}
                onRetry={() => void diff.refetch()}
                notes={notes}
                onNote={() => onView("review")}
              />
            </div>
            <div hidden={view !== "files"}>
              <FilesView
                scope={scope}
                run={turn}
                files={files}
                initialFile={initialFile}
                initialLine={initialLine}
                referenceVersion={reference?.version ?? (Number(query.get("ref")) || undefined)}
                enabled={view === "files"}
              />
            </div>
            <div hidden={view !== "terminal"}>
              <TerminalView scope={scope} run={turn} enabled={view === "terminal"} />
            </div>
          </>
        )}
      </div>
    </PanelFrame>
  );
}

function ReviewPanel({
  scope,
  reviews,
  run,
  onSelectReview,
  latestTurn,
  sessionId,
  loading,
  failed,
  onRetry,
  onAskFix,
  fixLabel,
  onReference,
}: {
  scope: Scope | undefined;
  reviews: Run[];
  run: Run | undefined;
  onSelectReview: (id: string) => void;
  latestTurn?: string;
  sessionId?: string;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  onAskFix?: (message: string) => void;
  fixLabel: string;
  onReference: (ref: string, review: Run) => void;
}) {
  const [tab, setTab] = useState<"summary" | "findings" | "evidence" | null>(null);
  const [saving, setSaving] = useState(false);
  const id = useId();
  const createIssue = useCreateIssue(scope);
  const queryClient = useQueryClient();
  const context = run?.review_context;
  const revision = text(context?.revision);
  const superseded = Boolean(context?.coding_run_id && context.session_id === sessionId && latestTurn && context.coding_run_id !== latestTurn);
  const findings = (run?.outputs ?? [])
    .filter((output) => output.kind === "finding")
    .flatMap((output) => output.items.map((item) => ({ item, outputId: output.id })));
  const detailTab = tab ?? (findings.length ? "findings" : "summary");
  const canCreate = isLive() ? Boolean(live.ws?.permissions?.includes("issues:write" as never)) : me()?.role !== "Guest";
  const createFromFinding = async (outputId: string, index: number, title: string, detail: string, fix: string) => {
    if (!scope || !run || saving) return;
    if (!isLive()) {
      const task = createTask({ project: scope.projectId, title, desc: `${detail}\n\n${fix}`, type: "bug" });
      openTask(task.id);
      return;
    }
    setSaving(true);
    try {
      const issue = await createIssue.mutateAsync({ title, description: `${detail}\n\n${fix}`.trim(), type: "bug", status: "todo", priority: "medium" });
      try {
        const updated = await unwrap(
          api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/outputs/{output_id}/items/{index}", {
            params: { path: { workspace_id: scope.workspaceId, project_id: scope.projectId, run_id: run.id, output_id: outputId, index } },
            body: { state: "done", link: issue.key },
          }),
        );
        queryClient.setQueryData(["review-run", run.id], updated);
        toast(`Created ${issue.key} from Juno's finding`);
      } catch {
        toast(`Created ${issue.key}, but the finding could not be linked.`, { kind: "err" });
      }
    } catch {
      // The issue mutation already reports its error.
    } finally {
      setSaving(false);
    }
  };
  // A finding as an issue in the project's GitHub repository, opened by the GitHub App at your request.
  const openOnGitHub = async (outputId: string, index: number) => {
    if (!scope || !run || saving) return;
    setSaving(true);
    try {
      const updated = await unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/agent/runs/{run_id}/outputs/{output_id}/items/{index}/github-issue", {
          params: { path: { workspace_id: scope.workspaceId, project_id: scope.projectId, run_id: run.id, output_id: outputId, index } },
        }),
      );
      queryClient.setQueryData(["review-run", run.id], updated);
      toast("Opened a GitHub issue from Juno's finding");
    } catch (error) {
      toast(error instanceof Error ? error.message : "GitHub didn't open the issue", { kind: "err" });
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="review-panel">
      <div className="row review-panel-head">
        <b>Juno · Review</b>
      </div>
      {reviews.length > 1 && (
        <select className="input" aria-label="Review" value={run?.id ?? ""} onChange={(event) => onSelectReview(event.target.value)}>
          {!run && <option value="">Select a review</option>}
          {reviews.map((review) => (
            <option key={review.id} value={review.id}>
              {text(review.review_context?.issue_key) || "Review"} · {new Date(review.created_at).toLocaleString()}
            </option>
          ))}
        </select>
      )}
      <div className="seg work-panel-nav" role="tablist" aria-label="Review details" onKeyDown={tabKeys}>
        {(["summary", "findings", "evidence"] as const).map((value) => (
          <button
            key={value}
            id={`${id}-${value}-tab`}
            role="tab"
            aria-selected={detailTab === value}
            aria-controls={`${id}-panel`}
            tabIndex={detailTab === value ? 0 : -1}
            className={detailTab === value ? "on" : ""}
            onClick={() => setTab(value)}
          >
            {value[0].toUpperCase() + value.slice(1)}
            {value === "findings" && findings.length ? ` ${findings.length}` : ""}
          </button>
        ))}
      </div>
      <div className="review-panel-body" role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${detailTab}-tab`}>
        {failed && (
          <p className="muted">
            Some reviews couldn't be loaded.{" "}
            <button className="btn btn-sm btn-ghost" onClick={onRetry}>
              Try again
            </button>
          </p>
        )}
        {!run ? (
          <p className="muted">
            {loading ? "Loading Juno's review…" : failed ? "The review is unavailable." : "No review yet. Juno's progress and findings will appear here."}
          </p>
        ) : (
          <>
            <div className="row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
              <span className="badge">{run.status.replaceAll("_", " ")}</span>
              {superseded && <span className="badge">Superseded by a later coding turn</span>}
            </div>
            {detailTab === "summary" ? (
              <>
                <div className="md">
                  <Markdown>{run.reply || run.error || "Juno is reviewing the recorded evidence…"}</Markdown>
                </div>
                <p className="faint">Juno's review is separate from human acceptance, passing checks, and merging.</p>
              </>
            ) : detailTab === "findings" ? (
              findings.length ? (
                findings.map(({ item, outputId }, index) => {
                  const finding = item.data as Record<string, unknown>;
                  const title = text(finding.title),
                    detail = text(finding.detail),
                    fix = text(finding.suggested_fix);
                  return (
                    <section className="panel review-finding" key={`${run.id}-${index}`}>
                      <span className="badge">{text(finding.severity) || "Finding"}</span>
                      {item.state !== "open" &&
                        (item.link?.startsWith("https://github.com/") ? (
                          <a className="badge" href={item.link} target="_blank" rel="noreferrer">
                            {item.state} · GitHub #{item.link.split("/").pop()}
                          </a>
                        ) : (
                          <span className="badge">
                            {item.state}
                            {item.link ? ` · ${item.link}` : ""}
                          </span>
                        ))}
                      <h3>{title}</h3>
                      <p>{detail}</p>
                      {fix && <p className="muted">Suggested fix: {fix}</p>}
                      {Array.isArray(finding.refs) && (
                        <ul>
                          {finding.refs.map((ref, i) => (
                            <li className="mono" key={i}>
                              {context?.coding_run_id ? (
                                <button className="btn btn-sm btn-ghost" onClick={() => onReference(text(ref), run)}>
                                  {text(ref)}
                                </button>
                              ) : (
                                text(ref)
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                        {canCreate && scope && item.state === "open" && (
                          <button className="btn btn-sm" disabled={saving} onClick={() => void createFromFinding(outputId, item.index, title, detail, fix)}>
                            Create issue
                          </button>
                        )}
                        {canCreate && scope && isLive() && context?.coding_run_id && item.state === "open" && (
                          <button className="btn btn-sm" disabled={saving} onClick={() => void openOnGitHub(outputId, item.index)}>
                            <Ic n="github" s={13} />
                            Open on GitHub
                          </button>
                        )}
                        {onAskFix && allowed("agents:code") && (
                          <button
                            className="btn btn-sm"
                            onClick={() =>
                              onAskFix(
                                `Address Juno's finding: ${title}\n\n${detail}\n\n${fix}\n\nEvidence: ${Array.isArray(finding.refs) ? finding.refs.join(", ") : "Not recorded"}`,
                              )
                            }
                          >
                            {fixLabel}
                          </button>
                        )}
                      </div>
                    </section>
                  );
                })
              ) : (
                <p className="muted">No findings recorded. This does not establish that all checks passed.</p>
              )
            ) : (
              <>
                <dl className="review-evidence">
                  <dt>Reviewed revision</dt>
                  <dd className="mono">{revision || "Not recorded"}</dd>
                  <dt>Coding turn</dt>
                  <dd className="mono">{text(context?.coding_run_id) || "Not linked to a coding turn"}</dd>
                  <dt>Verification</dt>
                  <dd>{text(context?.verification) || "Independent check results are unavailable; reported results remain unchecked."}</dd>
                </dl>
                {(run.sources ?? []).map((source) => (
                  <p key={source.label}>
                    <a href={source.url} target="_blank" rel="noreferrer">
                      {source.title || source.url}
                    </a>
                  </p>
                ))}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
