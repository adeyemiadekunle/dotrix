import { D } from "../data/store";
import { go } from "./nav";

/** The demo's agent requests can be reviewed in Inbox; Chat uses the live API. */
export function openDemoRequest({ thread, task }: { thread?: string; task?: string }) {
  const notification = D().notifs.find((n) => (thread && n.thread === thread) || (task && n.task === task && n.type === "approval"));
  go("inbox", {}, { search: notification ? `n=${encodeURIComponent(notification.id)}` : "tab=needs" });
}
