// Adapt sample data to the same list contract used by live sessions.
import type { CodingSession } from "@/lib/coding";
import type { Data } from "../data/types";

export function demoCodingSessions(data: Data): CodingSession[] {
  return data.coding.flatMap((session) => {
    const project = data.projects.find((item) => item.id === session.project);
    const issue = data.tasks.find((item) => item.id === session.task || item.key === session.task);
    if (!project || !issue) return [];
    return [
      {
        session_id: session.id,
        project_id: project.id,
        project_key: project.key,
        project_name: project.name,
        issue_key: issue.key,
        issue_title: issue.title,
        agent: session.tool,
        status: session.status,
        turns: session.turns.length,
        branch: session.branch ?? null,
        pr_number: session.pr?.number ?? null,
        pr_url: session.pr?.url ?? null,
        pr_state: session.pr?.state ?? null,
        state: session.state ?? "idle",
        title: session.title ?? issue.title,
        pinned: Boolean(session.pinned),
        archived: Boolean(session.archived),
        location: "cloud",
        started_at: new Date(session.at).toISOString(),
        updated_at: new Date(session.at).toISOString(),
      },
    ];
  });
}
