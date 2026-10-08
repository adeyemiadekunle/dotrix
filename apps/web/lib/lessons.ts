import type { Schemas } from "@pmagent/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, unwrap } from "@/lib/api";
import type { Scope } from "@/lib/issues";

export type Lesson = Schemas["LessonRead"];

const key = (scope: Scope | undefined) => ["lessons", scope?.projectId];
const path = (scope: Scope) => ({ workspace_id: scope.workspaceId, project_id: scope.projectId });

/** Lessons proposed from rejections and dismissals (owners and admins). */
export function useLessons(scope: Scope | undefined, enabled: boolean) {
  return useQuery({
    queryKey: key(scope),
    enabled: !!scope && enabled,
    queryFn: () =>
      unwrap(api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/lessons", { params: { path: path(scope!) } })),
  });
}

export function useDecideLesson(scope: Scope) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, accept, text }: { id: string; accept: boolean; text?: string }) =>
      accept
        ? unwrap(
            api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/lessons/{lesson_id}/accept", {
              params: { path: { ...path(scope), lesson_id: id } },
              body: { text: text || null },
            }),
          )
        : unwrap(
            api.POST("/v1/workspaces/{workspace_id}/projects/{project_id}/lessons/{lesson_id}/decline", {
              params: { path: { ...path(scope), lesson_id: id } },
            }),
          ),
    onSuccess: (lesson) => {
      toast.success(lesson.status === "accepted" ? `The ${lesson.agent} agent will follow it` : "Declined");
      void queryClient.invalidateQueries({ queryKey: key(scope) });
      void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}
