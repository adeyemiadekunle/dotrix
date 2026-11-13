import { ActionButton } from "@dotrix/ui/components/action-button";
import { useQuery } from "@tanstack/react-query";
import { api, errorMessage, unwrap, type Schemas } from "@/lib/api";
import { projectDiscussionHref, projectImplementationHref, projectStart } from "../core/projectSetup";

type Action = Schemas["ProjectReadiness"]["next_action"];
const labels: Record<Action, string> = {
  purpose: "Edit project purpose",
  knowledge: "Review project knowledge",
  repository: "Repository setup",
  models: "Your model settings",
  tasks: "Open project tasks",
  discuss: "Discuss with Nova",
  plan: "Plan implementation",
};
const states = {
  ready: "Saved evidence available",
  missing: "Not prepared",
  optional: "Optional",
  review: "Review needed",
  unverified: "Not verified live",
  blocked: "Needs attention",
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
  return (
    <section className="panel" aria-label="Project readiness" style={{ marginBottom: 16 }}>
      <div className="panel-h">
        <h2>Project readiness</h2>
      </div>
      <div className="panel-b">
        {!workspaceId ? (
          <p>Illustrative sample. Sign in to see readiness from your saved project and personal model access.</p>
        ) : (
          <>
            <p className="muted">Saved state, not a live integration test. You can manage tasks and knowledge without connecting a model.</p>
            {readiness.isPending && <p role="status">Loading saved readiness…</p>}
            {readiness.isError && <p role="alert">Readiness could not be loaded: {errorMessage(readiness.error)}. Project work remains available.</p>}
            {data && !readiness.isError && (
              <>
                <h3>{data.next_title}</h3>
                <p>{data.next_detail}</p>
                {data.next_allowed ? (
                  <a className="btn btn-primary btn-sm" href={links[data.next_action]}>
                    {labels[data.next_action]}
                  </a>
                ) : (
                  <p>{data.next_restriction}</p>
                )}
                {data.next_action !== "tasks" && (
                  <a className="btn btn-secondary btn-sm" href={links.tasks}>
                    Open project tasks
                  </a>
                )}
                <details open={!compact} style={{ marginTop: 16 }}>
                  <summary>Readiness details</summary>
                  <div className="stack" style={{ marginTop: 12 }}>
                    {data.checks.map((check) => (
                      <div key={check.key}>
                        <b>{check.title}</b> <span className="badge">{states[check.state]}</span>
                        <p>{check.detail}</p>
                        {check.key === "model" && data.model_success_at && (
                          <p className="faint">Recorded {new Date(data.model_success_at).toLocaleString()}.</p>
                        )}
                        {check.allowed ? (
                          <a className="btn btn-ghost btn-sm" href={links[check.action]}>
                            {labels[check.action]}
                          </a>
                        ) : (
                          <p className="muted">{check.restriction}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </details>
              </>
            )}
            <ActionButton className="btn btn-ghost btn-sm" disabled={readiness.isFetching} onClick={() => void readiness.refetch()}>
              Refresh saved readiness
            </ActionButton>
          </>
        )}
      </div>
    </section>
  );
}
