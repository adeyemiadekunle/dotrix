import { ISSUE_STATUSES } from "@pmagent/shared";
import { StatusBadge } from "@pmagent/ui";

// Placeholder home. Planned routes (FR-37): /[workspace]/[project]/{board,backlog,chat,briefing,approvals,settings}
export default function Home() {
  return (
    <main>
      <h1>pmagent</h1>
      <p>The AI project team for any project.</p>
      <ul>
        {ISSUE_STATUSES.map((s) => (
          <li key={s}>
            <StatusBadge status={s} />
          </li>
        ))}
      </ul>
    </main>
  );
}
