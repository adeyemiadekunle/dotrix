// Lessons proposed from rejections and dismissals, accepted into agent-rules/lessons/.
import type { Schemas } from "@dotrix/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "./api";
import type { Scope } from "./issues";

export type Lesson = Schemas["LessonRead"];

const projectPath = (s: Scope) => ({ workspace_id: s.workspaceId, project_id: s.projectId });
const listKey = (s: Scope) => ["lessons", s.projectId] as const;

export function useLessons(scope: Scope | undefined) {
  return useQuery({
    queryKey: scope ? listKey(scope) : ["lessons", "none"],
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/lessons", {
          params: { path: projectPath(scope!) },
        }),
      ),
    enabled: Boolean(scope),
  });
}

function useLessonMutation<Vars>(scope: Scope | undefined, fn: (scope: Scope, vars: Vars) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (vars: Vars) => fn(scope!, vars),
    onError: (e) => toast.error(errorMessage(e)),
    onSettled: () => {
      if (scope) {
        void queryClient.invalidateQueries({ queryKey: listKey(scope) });
        void queryClient.invalidateQueries({ queryKey: ["knowledge", scope.projectId] });
      }
    },
  });
}

/** Accept a proposed lesson: it lands in agent-rules/lessons/. */
export function useAcceptLesson(scope: Scope | undefined) {
  return useLessonMutation(scope, (s, { lessonId, body }: { lessonId: string; body: Schemas["LessonAccept"] }) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/lessons/{lesson_id}/accept", {
        params: { path: { ...projectPath(s), lesson_id: lessonId } },
        body,
      }),
    ),
  );
}

export function useDeclineLesson(scope: Scope | undefined) {
  return useLessonMutation(scope, (s, lessonId: string) =>
    unwrap(
      api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/lessons/{lesson_id}/decline", {
        params: { path: { ...projectPath(s), lesson_id: lessonId } },
      }),
    ),
  );
}
