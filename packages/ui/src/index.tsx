// Shared React components for web and desktop (board, issue cards, approval dialogs).
import type { IssueStatus } from "@pmagent/shared";

const STATUS_LABELS: Record<IssueStatus, string> = {
  todo: "To do",
  in_progress: "In progress",
  blocked: "Blocked",
  review: "In review",
  done: "Done",
};

export function StatusBadge({ status }: { status: IssueStatus }) {
  return <span data-status={status}>{STATUS_LABELS[status]}</span>;
}
