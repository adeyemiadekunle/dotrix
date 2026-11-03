import type { Scope } from "@/lib/issues";
import { useSharedCodingOutcomes } from "@/lib/coding";
import { closeDrawer } from "../core/actions";
import { go } from "../core/nav";

/** No sample/live mutation or private-session query is needed to read published evidence. */
export function SharedCodingOutcomes({ scope, issueKey }: { scope: Scope | undefined; issueKey: string }) {
  const query = useSharedCodingOutcomes(scope, issueKey);
  if (!scope) return null;
  if (query.isError) return <p role="alert">Published coding evidence could not be loaded.</p>;
  if (!query.data?.length) return null;
  return (
    <section aria-label="Published coding outcomes" style={{ marginTop: 12 }}>
      <h4>Published code and review</h4>
      {query.data.map((outcome) => (
        <article className="panel" key={outcome.pr_url} style={{ padding: "10px 12px", marginTop: 8 }}>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <a className="btn btn-sm btn-secondary" href={outcome.pr_url} target="_blank" rel="noreferrer">
              PR #{outcome.pr_number}
            </a>
            <span className={`badge ${outcome.pr_state === "merged" ? "green" : ""}`}>
              {outcome.pr_state === "merged"
                ? "Merged"
                : outcome.pr_state === "closed"
                  ? "Closed without merging"
                  : outcome.pr_state === "open"
                    ? "Open for review"
                    : "PR state unconfirmed"}
            </span>
            <span className="faint">
              Turn {outcome.turn}
              {outcome.commit_sha ? ` · ${outcome.commit_sha.slice(0, 8)}` : ""}
            </span>
          </div>
          <p className="muted" style={{ fontSize: 12.5, margin: "8px 0" }}>
            {outcome.pr_state === "merged"
              ? "The PR was merged on GitHub. A person confirms whether the task is complete."
              : outcome.pr_state === "closed"
                ? "This PR was closed without merging; it does not establish completion."
                : outcome.pr_state === "open"
                  ? "Published changes are not merged work. The task keeps its own status."
                  : "GitHub PR state is not confirmed here. The task keeps its own status."}
          </p>
          <p className="faint" style={{ fontSize: 12 }}>
            CI for this commit: {outcome.ci_state === "passed" ? "passed" : outcome.ci_state === "failed" ? "failed" : "not confirmed"}.
          </p>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            {outcome.review_url ? (
              <a className="btn btn-sm btn-ghost" href={outcome.review_url} target="_blank" rel="noreferrer">
                Juno review on GitHub
              </a>
            ) : (
              <span className="faint">No published review for this turn.</span>
            )}
            {outcome.ci_review_url && (
              <a className="btn btn-sm btn-ghost" href={outcome.ci_review_url} target="_blank" rel="noreferrer">
                CI review on GitHub
              </a>
            )}
            {outcome.session_id && (
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => {
                  closeDrawer();
                  go("codes", {}, { search: `session=${outcome.session_id}&from=issue` });
                }}
              >
                Open your coding session
              </button>
            )}
          </div>
        </article>
      ))}
    </section>
  );
}
