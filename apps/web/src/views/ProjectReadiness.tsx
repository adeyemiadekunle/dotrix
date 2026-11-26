import { useQuery } from "@tanstack/react-query";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api";
import { Ic } from "../core/icons";
import { projectDiscussionHref, projectImplementationHref, projectStart } from "../core/projectSetup";

type Action = Schemas["ProjectReadiness"]["next_action"];
type CheckState = Schemas["ProjectReadiness"]["checks"][number]["state"];

const labels: Record<Action, string> = {
  purpose: "Edit project purpose",
  knowledge: "Review project knowledge",
  repository: "Repository setup",
  models: "Your model settings",
  tasks: "Open project tasks",
  discuss: "Discuss with Nova",
  plan: "Plan implementation",
};

const states: Record<CheckState, string> = {
  ready: "Saved evidence available",
  missing: "Not prepared",
  optional: "Optional",
  review: "Review needed",
  unverified: "Not verified live",
  blocked: "Needs attention",
};

const badgeTone: Record<CheckState, string> = {
  ready: "badge green",
  missing: "badge amber",
  optional: "badge gray",
  review: "badge violet",
  unverified: "badge gray",
  blocked: "badge red",
};

const stateIcon: Record<CheckState, { name: string; color: string }> = {
  ready: { name: "circle-check", color: "var(--green)" },
  missing: { name: "circle-dot", color: "var(--amber)" },
  optional: { name: "circle-dashed", color: "var(--text-3)" },
  review: { name: "eye", color: "var(--violet)" },
  unverified: { name: "clock", color: "var(--text-3)" },
  blocked: { name: "triangle-alert", color: "var(--red)" },
};

export function ProjectReadiness({
  workspaceId,
  projectId,
  slug,
  projectKey,
  compact = false,
}: {
  workspaceId?: string;
  projectId: string;
  slug: string;
  projectKey: string;
  compact?: boolean;
}) {
  const readiness = useQuery({
    queryKey: ["project-readiness", workspaceId, projectId],
    enabled: !!workspaceId,
    staleTime: 0,
    refetchOnMount: "always",
    retry: false,
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/readiness", {
          params: { path: { workspace_id: workspaceId!, project_id: projectId } },
        }),
      ),
  });
  const data = readiness.data;
  const root = `/w/${slug}/p/${projectKey}`;
  const links: Record<Action, string> = {
    purpose: `${root}/overview#project-purpose`,
    knowledge: `${root}/knowledge${data?.source === "existing_repo" ? "?view=coverage" : ""}`,
    repository: `/onboarding?${new URLSearchParams({ workspace: workspaceId ?? "", project: projectId, mode: "project", step: "github" })}`,
    models: `/w/${slug}/settings/my-models`,
    tasks: `${root}/board`,
    discuss: data ? projectDiscussionHref(slug, projectKey, projectStart(data.source)) : root,
    plan: projectImplementationHref(slug, projectKey),
  };

  const readyCount = data ? data.checks.filter((c) => c.state === "ready").length : 0;
  const optionalCount = data ? data.checks.filter((c) => c.state === "optional").length : 0;
  const trackedCount = data ? data.checks.length - optionalCount : 0;

  return (
    <section className={`panel readiness-panel ${compact ? "compact" : ""}`} aria-label="Project readiness">
      <div className="panel-h readiness-head">
        <div className="row" style={{ gap: 8, minWidth: 0 }}>
          <span className="readiness-head-icon" aria-hidden="true">
            <Ic n="compass" s={14} />
          </span>
          <h2>Project readiness</h2>
          {data && (
            <span className={`badge ${readyCount === trackedCount && trackedCount > 0 ? "green" : "gray"}`}>
              {readyCount}/{trackedCount || data.checks.length} prepared
            </span>
          )}
        </div>
        {workspaceId && (
          <div className="acts">
            <button className="btn btn-ghost btn-sm" disabled={readiness.isFetching} onClick={() => void readiness.refetch()}>
              <Ic n="refresh-cw" s={12} />
              Refresh saved readiness
            </button>
          </div>
        )}
      </div>

      <div className="panel-b readiness-body">
        {!workspaceId ? (
          <p className="readiness-sample">Illustrative sample. Sign in to see readiness from your saved project and personal model access.</p>
        ) : (
          <>
            {readiness.isPending && (
              <p className="muted" role="status" style={{ margin: 0 }}>
                Loading saved readiness…
              </p>
            )}
            {readiness.isError && (
              <div className="alert danger" role="alert">
                <Ic n="triangle-alert" s={15} />
                <span>Readiness could not be loaded: {errorMessage(readiness.error)}. Project work remains available.</span>
              </div>
            )}
            {data && !readiness.isError && (
              <>
                <div className="readiness-next">
                  <div className="readiness-next-copy">
                    <span className="readiness-eyebrow">Recommended next step</span>
                    <h3>{data.next_title}</h3>
                    <p>{data.next_detail}</p>
                  </div>
                  <div className="readiness-actions">
                    {data.next_allowed ? (
                      <a className="btn btn-primary btn-sm" href={links[data.next_action]}>
                        {labels[data.next_action]}
                      </a>
                    ) : (
                      <p className="muted" style={{ margin: 0 }}>
                        {data.next_restriction}
                      </p>
                    )}
                    {data.next_action !== "tasks" && (
                      <a className="btn btn-secondary btn-sm" href={links.tasks}>
                        Open project tasks
                      </a>
                    )}
                  </div>
                </div>

                <details className="readiness-details" open={!compact}>
                  <summary className="readiness-summary">
                    <span className="readiness-chev" aria-hidden="true">
                      <Ic n="chevron-right" s={14} />
                    </span>
                    <span>Readiness details</span>
                    <span className="readiness-meta">
                      {readyCount} ready{optionalCount > 0 ? ` · ${optionalCount} optional` : ""}
                    </span>
                  </summary>
                  <div className="readiness-list">
                    {data.checks.map((check) => {
                      const icon = stateIcon[check.state];
                      return (
                        <div key={check.key} className="readiness-row">
                          <span className="readiness-row-ic" style={{ color: icon.color }} aria-hidden="true">
                            <Ic n={icon.name} s={15} />
                          </span>
                          <div className="readiness-row-main">
                            <div className="readiness-row-top">
                              <b>{check.title}</b>
                              <span className={badgeTone[check.state]}>{states[check.state]}</span>
                            </div>
                            <p>{check.detail}</p>
                            {check.key === "model" && data.model_success_at && (
                              <p className="faint readiness-stamp">Recorded {new Date(data.model_success_at).toLocaleString()}.</p>
                            )}
                            {!check.allowed && check.restriction && <p className="muted readiness-stamp">{check.restriction}</p>}
                          </div>
                          {check.allowed && (
                            <div className="readiness-row-act">
                              <a className="btn btn-secondary btn-sm" href={links[check.action]}>
                                {labels[check.action]}
                              </a>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </details>
              </>
            )}
            <p className="readiness-foot">Saved state, not a live integration test. You can manage tasks and knowledge without connecting a model.</p>
          </>
        )}
      </div>
    </section>
  );
}
