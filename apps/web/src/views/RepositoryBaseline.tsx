import { useRef, useState } from "react";
import type { Schemas } from "@/lib/api";
import { errorMessage } from "@/lib/api";
import type { Scope } from "@/lib/issues";
import { useRepoBaseline, useReviewRepoBaseline } from "@/lib/repo-knowledge";
import { allowed } from "../core/can";
import { go } from "../core/nav";

export function BaselineReview({ scope, projectKey }: { scope: Scope | undefined; projectKey: string }) {
  const query = useRepoBaseline(scope);
  const save = useReviewRepoBaseline(scope);
  const [notes, setNotes] = useState("");
  const [ackDigest, setAck] = useState<string | null>(null);
  const attempt = useRef<{ fingerprint: string; body: Schemas["BaselineReviewCreate"] } | null>(null);
  const baseline = query.data;
  const submit = (decision: "confirmed" | "corrections") => {
    if (!baseline || !scope || save.isPending) return;
    const data = { digest: baseline.digest, decision, notes, acknowledge_limits: ackDigest === baseline.digest };
    const fingerprint = JSON.stringify(data);
    if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, body: { ...data, request_id: crypto.randomUUID() } };
    save.mutate(attempt.current.body);
  };
  return (
    <section className="panel" aria-label="Repository baseline" style={{ marginBottom: 16 }}>
      <div className="panel-h">
        <h2>Review the repository baseline</h2>
        <button className="btn btn-sm btn-ghost" disabled={query.isFetching || save.isPending} onClick={() => void query.refetch()}>
          Reload baseline
        </button>
      </div>
      <div className="panel-b">
        <p>1. Take an inventory. 2. Explain the repository. 3. Read the cited wiki pages and add project context. 4. Review before planning changes.</p>
        <p className="muted">
          Repository access and read files do not prove full understanding. Code cannot establish your goals, requirements or the reasons behind past decisions.
          Add these below or in Knowledge; observations and inferences in wiki pages must stay distinct.
        </p>
        <p className="faint">Confirming the baseline does not approve implementation. Normal change approvals and the human merge decision still apply.</p>
        {query.isLoading && <p role="status">Loading baseline…</p>}
        {query.isError && <p role="alert">{errorMessage(query.error)}</p>}
        {baseline && (
          <>
            <p role="status">
              {baseline.current
                ? "Reviewed scope — current evidence matches the human review."
                : baseline.review?.digest !== baseline.digest && baseline.review
                  ? "Evidence changed — review this baseline again."
                  : baseline.review?.decision === "corrections"
                    ? "Corrections requested — resolve them before planning."
                    : "Not yet confirmed by a person."}
            </p>
            {baseline.blockers.map((blocker) => (
              <p className="muted" key={blocker}>
                {blocker}
              </p>
            ))}
            {baseline.human_context && (
              <div aria-label="Current shared human context">
                <b>Current shared human context</b>
                <p style={{ whiteSpace: "pre-wrap" }}>{baseline.human_context.notes}</p>
              </div>
            )}
            {baseline.review && (
              <div>
                <b>Latest shared review: {baseline.review.decision}</b>
                <p style={{ whiteSpace: "pre-wrap" }}>{baseline.review.notes || "No additional notes."}</p>
                <small>Reviewed {new Date(baseline.review.created_at).toLocaleString()}; applies only to its saved evidence revision.</small>
              </div>
            )}
            {scope && allowed("knowledge:write") && (
              <>
                <label className="field">
                  Shared goals, constraints, corrections and open questions
                  <textarea className="textarea" maxLength={8000} value={notes} disabled={save.isPending} onChange={(e) => setNotes(e.target.value)} />
                </label>
                <p className="faint">
                  Leave blank to keep the current shared context. Enter a revised version to replace it. These notes are shared with people who can see this
                  project. Your private conversations stay private. Existing requirements and decisions are not overwritten.
                </p>
                <label>
                  <input
                    type="checkbox"
                    checked={ackDigest === baseline.digest}
                    disabled={save.isPending || query.isFetching}
                    onChange={(e) => setAck(e.target.checked ? baseline.digest : null)}
                  />{" "}
                  I reviewed the cited pages, coverage gaps and exclusions; this confirms the reviewed scope, not complete understanding.
                </label>
                <div className="row" style={{ marginTop: 12, gap: 8 }}>
                  <button
                    className="btn btn-primary"
                    disabled={save.isPending || query.isFetching || query.isError || !baseline.can_confirm || ackDigest !== baseline.digest}
                    onClick={() => submit("confirmed")}
                  >
                    Confirm reviewed baseline
                  </button>
                  <button
                    className="btn btn-secondary"
                    disabled={save.isPending || query.isFetching || query.isError || !notes.trim()}
                    onClick={() => submit("corrections")}
                  >
                    Save corrections and context
                  </button>
                </div>
                {save.isError && <p role="alert">{errorMessage(save.error)} The draft is retained; reload the evidence before retrying a changed baseline.</p>}
              </>
            )}
            {baseline.current && !query.isError && !query.isFetching && (
              <button
                className="btn btn-secondary"
                style={{ marginTop: 12 }}
                onClick={() =>
                  go(
                    "chat",
                    {},
                    {
                      search: new URLSearchParams({
                        project: projectKey,
                        mode: "plan",
                        q: "Use the reviewed repository baseline and shared goals to propose the next useful scope. Check its freshness, distinguish evidence from assumptions and ask about unresolved questions. Do not implement until I explicitly request Build mode.",
                      }).toString(),
                    },
                  )
                }
              >
                Plan from reviewed baseline
              </button>
            )}
          </>
        )}
      </div>
    </section>
  );
}
