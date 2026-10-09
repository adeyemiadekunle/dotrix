import type { Schemas } from "@pmagent/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "@/lib/api";
import type { Scope } from "@/lib/issues";

export type Automation = Schemas["AutomationRead"];
export type AutomationCreate = Schemas["AutomationCreate"];
export type AutomationEvent = Schemas["AutomationEvent"];

const key = (scope: Scope | undefined) => ["automations", scope?.projectId];
const path = (scope: Scope) => ({ workspace_id: scope.workspaceId, project_id: scope.projectId });

export const EVENT_LABELS: Record<AutomationEvent, string> = {
  "issue.created": "Someone creates an issue",
  "issue.done": "Someone finishes an issue",
  "document.changed": "Someone edits a document",
  "changes.approved": "An agent's changes are approved",
  "code.pushed": "Code is pushed to the repository",
};

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** "Every Monday at 08:00 UTC · when someone finishes an issue" */
export function describeWhen(a: Pick<Automation, "events" | "schedule_hour" | "schedule_weekday">): string {
  const parts: string[] = [];
  if (a.schedule_hour !== null && a.schedule_hour !== undefined) {
    const at = `${String(a.schedule_hour).padStart(2, "0")}:00 UTC`;
    parts.push(a.schedule_weekday !== null && a.schedule_weekday !== undefined ? `Every ${WEEKDAYS[a.schedule_weekday]} at ${at}` : `Every day at ${at}`);
  }
  if (a.events.length) parts.push(`when ${a.events.map((e) => EVENT_LABELS[e].replace(/^Someone /, "someone ").replace(/^An /, "an ").replace(/^Code /, "code ")).join(", or ")}`);
  const text = parts.join(", and ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Ready-made automations to start from. */
export const PRESETS: { id: string; label: string; body: AutomationCreate }[] = [
  {
    id: "docs",
    label: "Keep documents current",
    body: {
      name: "Keep documents current",
      agent: "documentation",
      events: ["changes.approved", "issue.done"],
      instructions:
        "Bring /pmagent/current-state.md and /pmagent/roadmap.md up to date with what just changed, and any other document it makes stale. Propose only the edits that are needed; change nothing else.",
      max_runs_per_day: 5,
      enabled: true,
      unattended: false,
    },
  },
  {
    id: "weekly",
    label: "Weekly status",
    body: {
      name: "Weekly status",
      agent: "auto",
      events: [],
      schedule_hour: 7,
      schedule_weekday: 0,
      instructions:
        "Write this week's status into /pmagent/current-state.md: what got done, what's in progress, what's blocked, and what's next. Keep it short.",
      max_runs_per_day: 1,
      enabled: true,
      unattended: false,
    },
  },
  {
    id: "triage",
    label: "Triage new issues",
    body: {
      name: "Triage new issues",
      agent: "auto",
      events: ["issue.created"],
      instructions:
        "Look at the new issues: find duplicates on the board and in the documents, and propose a type, priority, and links for each, or a comment on the issue it repeats.",
      max_runs_per_day: 10,
      enabled: true,
      unattended: false,
    },
  },
  {
    id: "review",
    label: "Review pushes",
    body: {
      name: "Review pushes",
      agent: "reviewer",
      events: ["code.pushed"],
      instructions:
        "Check what was just pushed against the requirements and the open issues. Record anything missing or at odds as findings; don't change anything.",
      max_runs_per_day: 5,
      enabled: true,
      unattended: false,
    },
  },
  {
    id: "watch",
    label: "Watch a topic",
    body: {
      name: "Watch: <topic>",
      agent: "research",
      events: [],
      schedule_hour: 6,
      schedule_weekday: 0,
      instructions:
        "Re-check <the topic: a regulation, a competitor, a dependency's releases and security advisories> on the web. Compare with the newest note on it in /pmagent/research/. If nothing material changed, say so in one line and propose nothing. If something did, report only what changed, with sources, and propose updating the note (and any requirement or decision it affects).",
      max_runs_per_day: 1,
      enabled: true,
      unattended: false,
    },
  },
  {
    id: "stale",
    label: "Flag stale documents",
    body: {
      name: "Flag stale documents",
      agent: "documentation",
      events: [],
      schedule_hour: 7,
      schedule_weekday: 4,
      instructions:
        "Go through the documents the project context lists as possibly out of date. For each, check with graph_neighbors what changed, and propose the edits that bring it up to date; leave alone what's still right.",
      max_runs_per_day: 1,
      enabled: true,
      unattended: false,
    },
  },
];

export function useAutomations(scope: Scope | undefined) {
  return useQuery({
    queryKey: key(scope),
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/automations", { params: { path: path(scope!) } })),
    enabled: Boolean(scope),
  });
}

export function useSaveAutomation(scope: Scope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: AutomationCreate }) =>
      id
        ? unwrap(
            api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
              params: { path: { ...path(scope), automation_id: id } },
              body: { ...body, schedule_hour: body.schedule_hour ?? null, schedule_weekday: body.schedule_weekday ?? null },
            }),
          )
        : unwrap(api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/automations", { params: { path: path(scope) }, body })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: key(scope) }),
  });
}

export function useToggleAutomation(scope: Scope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      unwrap(
        api.PATCH("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
          params: { path: { ...path(scope), automation_id: id } },
          body: { enabled },
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: key(scope) }),
  });
}

export function useDeleteAutomation(scope: Scope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}", {
          params: { path: { ...path(scope), automation_id: id } },
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: key(scope) }),
  });
}

export function useRunAutomation(scope: Scope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/automations/{automation_id}/run", {
          params: { path: { ...path(scope), automation_id: id } },
        }),
      ),
    onSuccess: (a) =>
      a.last_error ? toast.error(a.last_error) : toast.success(`${a.name} is running; its replies are in Chat`),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: key(scope) });
      void queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}
