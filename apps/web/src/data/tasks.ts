// Tasks for the screens that show them: the API's issues (TanStack Query) in a real workspace,
// the store's in the seeded one. A screen reads them here and doesn't know which it has.
import { useIssue } from "../../lib/issues";
import { logActivity, logComment, toAttachment } from "../../lib/view-models";
import {
  useLiveAllTasks,
  useLiveArchivedTasks,
  useLiveMyTasks,
  useLiveProjectTasks,
  useLiveStarredTasks,
  useLiveWorkspaceTasks,
} from "../../lib/workspace-data";
import { isMine, personal } from "../core/features";
import { isLive, live, liveCommentsOf } from "./live";
import { mdToHtml } from "./markdown";
import { D, allTasks, canSee, commentsOf, proj, task, tasksOf } from "./store";
import type { Activity, Attachment, Comment, Task } from "./types";

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

/** One task by id (the open drawer), archived or not, and a lookup for the tasks it names (its "Blocked by").
 * A real workspace reads the workspace's issues query; a task it doesn't hold yet falls back to the store's. */
export function useTask(id: string | null | undefined): { task: Task | undefined; find: (id: string) => Task | undefined } {
  const on = isLive();
  const rows = useLiveWorkspaceTasks(live.ws?.id, on);
  const find = (x: string) => (on ? rows?.find((t) => t.id === x) : undefined) ?? task(x);
  return { task: id ? find(id) : undefined, find };
}

/** What a task's list row doesn't carry: its description, comments, activity and files.
 * `state` is "loading" or "error" until a real workspace's issue has answered; `retry` asks again. */
export function useTaskDetail(t: Task | undefined): {
  desc: string;
  comments: Comment[];
  activity: Activity[];
  attachments: Attachment[];
  state: "ready" | "loading" | "error";
  retry: () => void;
} {
  const on = isLive();
  const issue = useIssue(on && live.ws && t ? { workspaceId: live.ws.id, projectId: t.project } : undefined, on && t ? t.key : null);
  if (!t) return { desc: "", comments: [], activity: [], attachments: [], state: "ready", retry: () => {} };
  if (!on)
    return {
      desc: t.desc,
      comments: commentsOf(t.id),
      activity: D().activity.filter((a) => a.task === t.id),
      attachments: t.attachments,
      state: "ready",
      retry: () => {},
    };
  const log = issue.data?.log ?? [];
  return {
    desc: mdToHtml(issue.data?.description ?? ""),
    comments: log.filter((e) => e.kind === "commented" && e.body).map((e) => logComment(e, t.id)),
    activity: log
      .filter((e) => e.kind !== "commented")
      .map((e) => logActivity(e, t.id))
      .reverse(),
    attachments: (issue.data?.attachments ?? []).map(toAttachment),
    state: issue.data ? "ready" : issue.isError ? "error" : "loading",
    retry: () => void issue.refetch(),
  };
}

/** How many comments a task has. */
export const commentCount = (t: Task) => (isLive() ? (t.commentCount ?? liveCommentsOf(t).length) : commentsOf(t.id).length);
