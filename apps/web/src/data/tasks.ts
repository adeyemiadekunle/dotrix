// Tasks for the screens that show them: the API's issues (TanStack Query) in a real workspace,
// the store's in the seeded one. A screen reads them here and doesn't know which it has.
import { useLiveAllTasks, useLiveArchivedTasks, useLiveMyTasks, useLiveProjectTasks, useLiveStarredTasks } from "../../lib/workspace-data";
import { isMine, personal } from "../core/features";
import { isLive, live, liveCommentsOf } from "./live";
import { D, allTasks, canSee, commentsOf, proj, tasksOf } from "./store";
import type { Task } from "./types";

/** What a screen gets: `loading` until the API's first answer (never in the seeded workspace). */
type Tasks = { tasks: Task[]; loading: boolean };
const from = (on: boolean, api: Task[] | undefined, store: () => Task[]): Tasks =>
  on ? { tasks: api ?? [], loading: !api } : { tasks: store(), loading: false };

/** A project's tasks that aren't archived, in its own order. */
export function useProjectTasks(projectId: string): Tasks {
  const on = isLive();
  return from(on, useLiveProjectTasks(live.ws?.id, projectId, on), () => tasksOf(projectId));
}

/** Every task that isn't archived, in the projects you can see. */
export function useAllTasks(): Tasks {
  const on = isLive();
  return from(on, useLiveAllTasks(live.ws?.id, on), allTasks);
}

/** Your tasks: the ones assigned to you, or every task in a personal workspace. */
export function useMyTasks(): Tasks {
  const on = isLive();
  const solo = personal();
  const mine = useLiveMyTasks(live.ws?.id, on && !solo);
  const all = useLiveAllTasks(live.ws?.id, on && solo);
  const got = from(on, solo ? all : mine, allTasks);
  return { ...got, tasks: got.tasks.filter(isMine) };
}

/** The tasks you starred. */
export function useStarredTasks(): Tasks {
  const on = isLive();
  return from(on, useLiveStarredTasks(live.ws?.id, on), () => allTasks().filter((t) => t.fav));
}

/** Archived tasks, the latest archived first. */
export function useArchivedTasks(): Tasks {
  const on = isLive();
  return from(on, useLiveArchivedTasks(live.ws?.id, on), () =>
    D()
      .tasks.filter((t) => t.archived && canSee(proj(t.project)) && !proj(t.project)?.archived)
      .sort((a, b) => (b.archivedAt || 0) - (a.archivedAt || 0)),
  );
}

/** How many comments a task has. */
export const commentCount = (t: Task) => (isLive() ? (t.commentCount ?? liveCommentsOf(t).length) : commentsOf(t.id).length);
