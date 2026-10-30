// The right side panel beside a coding session (Coding) or a conversation (Chat), resizable by its left edge.
// Coding: the selected turn's Changes, Files, Terminal, and Juno's Review, as tabs.
// Chat: the files and terminal of the session the conversation started, one above the other, no tabs.
// Both: a turn picker and a close button in the header; on narrow screens the panel floats over the page.
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
import { ChangesView, FilesView, TerminalView } from "./TurnViews";

const text = (value: unknown) => (typeof value === "string" ? value : "");
const narrowPanel = () => window.matchMedia("(max-width: 1200px)").matches;
type CodingTab = "changes" | "files" | "terminal" | "review";

/** The panel's frame: the drag edge, a one-line header (what it shows, the turn, close), and the body. */
function PanelFrame({
  label,
  widthKey,
  title,
  tools,
  onClose,
  closeLabel = "Close the panel",
  children,
}: {
  label: string;
  widthKey: string;
  title: ReactNode;
  tools?: ReactNode;
  onClose: () => void;
  closeLabel?: string;
  children: ReactNode;
}) {
  const [width, setWidth] = useStoredSize(widthKey, 460, 300, 960);
  const closeButton = useRef<HTMLButtonElement>(null);
  // Floating over the page on narrow screens: focus moves in, and Escape closes it.
  useEffect(() => {
    if (!narrowPanel()) return;
    const previous = document.activeElement;
    closeButton.current?.focus();
    return () => {
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && narrowPanel()) onClose();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);
  return (
    <aside className="side-panel" style={{ width }} aria-label={label}>
      <Splitter dir="col" className="side-panel-split" label="Resize the panel" onDrag={(delta) => setWidth((w) => w - delta)} />
      <div className="side-panel-head">
        {title}
        <span className="sp" />
        {tools}
        <button ref={closeButton} className="ibtn ibtn-sm" onClick={onClose} aria-label={closeLabel} data-tip="Close">
          <Ic n="x" s={14} />
        </button>
      </div>
      {children}
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

/** Coding: a session's turn as tabs (Changes, Files, Terminal, Review). */
export function CodingPanel({
  scope,
  cs,
  initial = "changes",
  onClose,
  onAskFix,
  fixLabel,
}: {
  scope: Scope | undefined;
  cs: CodingSession;
  initial?: "changes" | "review";
  onClose: () => void;
  onAskFix?: (message: string) => void;
  fixLabel: string;
}) {
  const query = useRoute().search;
  const [tab, setTab] = useState<CodingTab>(() => (initial === "review" ? "review" : query.has("file") ? "files" : "changes"));
  const { turnsQuery, turns, turn, setPicked, diff, files } = useTurn(scope, cs, query.get("turn"));
  const [selectedReview, setSelectedReview] = useState<string | null>(null);
  const [reference, setReference] = useState<{ turn: string; path: string; line?: number; version: number } | null>(null);
  const id = useId();
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
  const findingCount = (review?.outputs ?? []).filter((output) => output.kind === "finding").reduce((count, output) => count + output.items.length, 0);
  const initialFile =
    reference && reference.turn === turn?.id
      ? reference.path
      : !query.get("turn") || query.get("turn") === turn?.id
        ? (query.get("file") ?? undefined)
        : undefined;
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
    if (cs.session_id === session) {
      setPicked(turn);
      setReference((previous) => ({ turn, path, line, version: (previous?.version ?? 0) + 1 }));
      setTab("files");
    } else {
      const search = new URLSearchParams({ session, turn, file: path, panel: "changes" });
      if (line) search.set("line", String(line));
      go("coding", {}, { search: search.toString() });
    }
  };
  const tabs: { id: CodingTab; label: string; icon: string; count?: number }[] = [
    { id: "changes", label: "Changes", icon: "git-compare", count: files.length },
    { id: "files", label: "Files", icon: "folder-tree" },
    { id: "terminal", label: "Terminal", icon: "square-terminal" },
    { id: "review", label: "Review", icon: "shield-check", count: findingCount },
  ];
  const panelOf = (which: CodingTab, body: ReactNode) => (
    <section role="tabpanel" id={`${id}-${which}-panel`} aria-labelledby={`${id}-${which}-tab`} hidden={tab !== which} className="side-panel-body">
      {body}
    </section>
  );
  return (
    <PanelFrame
      label="Session work"
      widthKey="dotrix.coding.panel.width"
      onClose={onClose}
      title={
        <div className="side-tabs" role="tablist" aria-label="Session work" onKeyDown={tabKeys}>
          {tabs.map((item) => (
            <button
              key={item.id}
              id={`${id}-${item.id}-tab`}
              role="tab"
              aria-selected={tab === item.id}
              aria-controls={`${id}-${item.id}-panel`}
              tabIndex={tab === item.id ? 0 : -1}
              onClick={() => setTab(item.id)}
            >
              <Ic n={item.icon} s={13} />
              <span>{item.label}</span>
              {!!item.count && <span className="side-tab-count">{item.count}</span>}
            </button>
          ))}
        </div>
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
      {panelOf(
        "changes",
        turn ? (
          <ChangesView run={turn} files={files} loading={diff.isLoading} error={diff.isError} onRetry={() => void diff.refetch()} />
        ) : (
          <NoTurn query={turnsQuery} />
        ),
      )}
      {panelOf(
        "files",
        turn ? (
          <FilesView
            scope={scope}
            run={turn}
            files={files}
            initialFile={initialFile}
            initialLine={initialLine}
            referenceVersion={reference?.version}
            enabled={tab === "files"}
          />
        ) : (
          <NoTurn query={turnsQuery} />
        ),
      )}
      {panelOf("terminal", turn ? <TerminalView scope={scope} run={turn} enabled={tab === "terminal"} /> : <NoTurn query={turnsQuery} />)}
      {panelOf(
        "review",
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
                  if (narrowPanel()) onClose();
                }
              : undefined
          }
          fixLabel={fixLabel}
          onReference={openReference}
        />,
      )}
    </PanelFrame>
  );
}

/** Chat: the files and terminal of the session a conversation started, stacked, no tabs; the line between them drags. */
export function ChatPanel({ scope, cs, onClose }: { scope: Scope | undefined; cs: CodingSession; onClose: () => void }) {
  const { turnsQuery, turns, turn, setPicked, files } = useTurn(scope, cs, null);
  const [filesH, setFilesH] = useStoredSize("dotrix.chat.panel.filesHeight", 360, 120, 1200);
  return (
    <PanelFrame
      label="Files and terminal"
      widthKey="dotrix.chat.panel.width"
      onClose={onClose}
      title={
        <span className="side-panel-title trunc">
          <Ic n="square-terminal" s={14} />
          <span className="mono faint">{cs.issue_key}</span>
        </span>
      }
      tools={<TurnPicker turns={turns} turn={turn} onPick={setPicked} />}
    >
      {turn ? (
        <div className="side-stack">
          <section className="side-pane" aria-label="Files" style={{ flexBasis: filesH }}>
            <div className="side-pane-head">
              <Ic n="folder-tree" s={13} />
              Files
            </div>
            <div className="side-panel-body">
              <FilesView scope={scope} run={turn} files={files} />
            </div>
          </section>
          <Splitter dir="row" className="side-stack-split" label="Resize the files and terminal" onDrag={(delta) => setFilesH((h) => h + delta)} />
          <section className="side-pane grow-pane" aria-label="Terminal">
            <div className="side-pane-head">
              <Ic n="square-terminal" s={13} />
              Terminal
              <span className="sp" />
              <span className="faint">Recorded output · read-only</span>
            </div>
            <div className="side-panel-body">
              <TerminalView scope={scope} run={turn} />
            </div>
          </section>
        </div>
      ) : (
        <div className="side-panel-body">
          <NoTurn query={turnsQuery} />
        </div>
      )}
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
                      {item.state !== "open" && (
                        <span className="badge">
                          {item.state}
                          {item.link ? ` · ${item.link}` : ""}
                        </span>
                      )}
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
