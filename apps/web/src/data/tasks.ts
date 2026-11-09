// A project's tasks for the screens that show them: the API's issues (TanStack Query) in a real
// workspace, the store's in the seeded one. A screen reads them here and doesn't know which it has.
import { useLiveProjectTasks } from "../../lib/workspace-data";
import { isLive, live, liveCommentsOf } from "./live";
import { commentsOf, tasksOf } from "./store";
import type { Task } from "./types";

/** A project's tasks that aren't archived, in its own order. `loading` until the first answer from the API. */
export function useProjectTasks(projectId: string): { tasks: Task[]; loading: boolean } {
  const on = isLive();
  const fromApi = useLiveProjectTasks(live.ws?.id, projectId, on);
  if (!on) return { tasks: tasksOf(projectId), loading: false };
  return { tasks: fromApi ?? [], loading: !fromApi };
}

/** How many comments a task has. */
export const commentCount = (t: Task) => (isLive() ? (t.commentCount ?? liveCommentsOf(t).length) : commentsOf(t.id).length);
