import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { Run } from "@/lib/agent";
import { api, unwrap } from "@/lib/api";
import { useCodingSession, type CodingSession } from "@/lib/coding";
import { useCreateIssue, type Scope } from "@/lib/issues";
import { useReviewRuns, type SpecialistTask } from "@/lib/team";
import { Markdown } from "@/components/markdown";
import { createTask, openTask } from "../core/actions";
import { allowed } from "../core/can";
import { Ic } from "../core/icons";
import { go, useRoute } from "../core/nav";
import { isLive, live } from "../data/live";
import { me } from "../data/store";
import { Splitter, useStoredSize } from "../ui/splitter";
import { toast } from "../ui/toast";
import { KaiPanel } from "./KaiPanel";

const text = (value: unknown) => (typeof value === "string" ? value : "");

export function WorkPanels({
  scope,
  cs,
  tasks = [],
  roots = [],
  initial = "coding",
  onClose,
  onAskFix,
}: {
  scope: Scope | undefined;
  cs?: CodingSession | null;
  tasks?: SpecialistTask[];
  roots?: Run[];
  initial?: "coding" | "review";
  onClose: () => void;
  onAskFix?: (message: string) => void;
}) {
  const [picked, setPicked] = useState<"coding" | "review" | null>(null);
  useEffect(() => setPicked(null), [initial]);
  const query = useRoute().search;
  const [reference, setReference] = useState<{ turn: string; path: string } | null>(null);
  const selected = picked ?? initial;
  const turns = useCodingSession(scope, cs?.session_id ?? "").data ?? [];
  const latestChanged = [...turns].reverse().find((turn) => turn.files_changed.length && ["pr_opened", "changes_ready"].includes(turn.status));
  const ids = [
    ...tasks.filter((task) => task.agent === "reviewer").map((task) => task.id),
    ...roots.filter((run) => run.agent === "reviewer").map((run) => run.id),
    ...turns.flatMap((turn) => (turn.review_run_id ? [turn.review_run_id] : [])),
  ];
  const reviews = useReviewRuns(scope, ids);
  const openReference = (ref: string, review: Run) => {
    const path = ref.replace(/:\d+(?:[-:]\d+)?$/, "");
    const turn = text(review.review_context?.coding_run_id),
      session = text(review.review_context?.session_id);
    if (!turn || !session || path.startsWith("/") || path.includes("..")) return;
    if (cs?.session_id === session) {
      setReference({ turn, path });
      setPicked("coding");
    } else go("chat", {}, { search: new URLSearchParams({ tab: "coding", session, turn, file: path }).toString() });
  };
  const navigation = (
    <div
      className="seg work-panel-nav"
      role="tablist"
      aria-label="Agent work"
      onKeyDown={(event) => {
        if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
          event.preventDefault();
          setPicked(selected === "coding" || !cs ? "review" : "coding");
          (event.currentTarget.querySelector(`button:nth-child(${selected === "coding" ? 2 : 1})`) as HTMLButtonElement | null)?.focus();
        }
      }}
    >
      <button role="tab" aria-selected={selected === "coding"} className={selected === "coding" ? "on" : ""} disabled={!cs} onClick={() => setPicked("coding")}>
        Kai · Coding
      </button>
      <button role="tab" aria-selected={selected === "review"} className={selected === "review" ? "on" : ""} onClick={() => setPicked("review")}>
        Juno · Review
      </button>
    </div>
  );
  return selected === "coding" && cs ? (
    <KaiPanel
      key={reference?.turn ?? query.get("turn") ?? cs.session_id}
      cs={cs}
      onClose={onClose}
      navigation={navigation}
      initialTurn={reference?.turn ?? query.get("turn") ?? undefined}
      initialFile={reference?.path ?? query.get("file") ?? undefined}
    />
  ) : (
    <ReviewPanel
      scope={scope}
      reviews={reviews}
      latestTurn={latestChanged?.id}
      sessionId={cs?.session_id}
      navigation={navigation}
      onClose={onClose}
      onAskFix={onAskFix}
      onReference={openReference}
    />
  );
}

function ReviewPanel({
  scope,
  reviews,
  latestTurn,
  sessionId,
  navigation,
  onClose,
  onAskFix,
  onReference,
}: {
  scope: Scope | undefined;
  reviews: Run[];
  latestTurn?: string;
  sessionId?: string;
  navigation: ReactNode;
  onClose: () => void;
  onAskFix?: (message: string) => void;
  onReference: (ref: string, review: Run) => void;
}) {
  const [width, setWidth] = useStoredSize("dotrix.chat.kaiPanel.width", 420, 300, 900);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"summary" | "findings" | "evidence">("summary");
  const [saving, setSaving] = useState(false);
  const createIssue = useCreateIssue(scope);
  const queryClient = useQueryClient();
  const sorted = useMemo(() => [...reviews].sort((a, b) => b.created_at.localeCompare(a.created_at)), [reviews]);
  const run = sorted.find((review) => review.id === selected) ?? sorted[0];
  const context = run?.review_context;
  const revision = text(context?.revision);
  const superseded = Boolean(context?.coding_run_id && context.session_id === sessionId && latestTurn && context.coding_run_id !== latestTurn);
  const findings = (run?.outputs ?? [])
    .filter((output) => output.kind === "finding")
    .flatMap((output) => output.items.map((item) => ({ item, outputId: output.id })));
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
    <aside className="kai-panel review-panel" style={{ width }} aria-label="Juno's review">
      <Splitter dir="col" className="kai-panel-split" label="Resize the panel" onDrag={(delta) => setWidth((w) => w - delta)} />
      {navigation}
      <div className="row review-panel-head">
        <b>Juno · Review</b>
        <span className="sp" />
        <button className="ibtn ibtn-sm" onClick={onClose} aria-label="Close the review panel">
          <Ic n="x" s={14} />
        </button>
      </div>
      {sorted.length > 1 && (
        <select className="input" aria-label="Review" value={run?.id ?? ""} onChange={(event) => setSelected(event.target.value)}>
          {sorted.map((review) => (
            <option key={review.id} value={review.id}>
              {text(review.review_context?.issue_key) || "Review"} · {new Date(review.created_at).toLocaleString()}
            </option>
          ))}
        </select>
      )}
      <div
        className="seg work-panel-nav"
        role="tablist"
        aria-label="Review details"
        onKeyDown={(event) => {
          if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
            event.preventDefault();
            const tabs = ["summary", "findings", "evidence"] as const;
            const next = (tabs.indexOf(tab) + (event.key === "ArrowRight" ? 1 : 2)) % 3;
            setTab(tabs[next]!);
            (event.currentTarget.children[next] as HTMLButtonElement)?.focus();
          }
        }}
      >
        {(["summary", "findings", "evidence"] as const).map((value) => (
          <button key={value} role="tab" aria-selected={tab === value} className={tab === value ? "on" : ""} onClick={() => setTab(value)}>
            {value[0].toUpperCase() + value.slice(1)}
            {value === "findings" && findings.length ? ` ${findings.length}` : ""}
          </button>
        ))}
      </div>
      <div className="kai-panel-body">
        {!run ? (
          <p className="muted">No review yet. Juno's progress and findings will appear here.</p>
        ) : (
          <>
            <div className="row" style={{ gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
              <span className="badge">{run.status.replaceAll("_", " ")}</span>
              {superseded && <span className="badge">Superseded by a later coding turn</span>}
            </div>
            {tab === "summary" ? (
              <>
                <div className="md">
                  <Markdown>{run.reply || run.error || "Juno is reviewing the recorded evidence…"}</Markdown>
                </div>
                <p className="faint">Juno's review is separate from human acceptance, passing checks, and merging.</p>
              </>
            ) : tab === "findings" ? (
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
                            Ask Nova to fix
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
    </aside>
  );
}
