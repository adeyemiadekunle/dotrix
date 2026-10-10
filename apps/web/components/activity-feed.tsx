import { Avatar, AvatarFallback, AvatarImage } from "@dotrix/ui/components/avatar";
import { BotIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import type { ReactNode } from "react";

import { FIELD_LABELS, show, timeAgo } from "@/components/issues/issue-activity";
import { AGENT_LABELS, type MemberMap } from "@/components/issues/meta";
import { ProjectTile } from "@/components/project-tile";
import type { ActivityItem } from "@/lib/activity";
import { initials } from "@/lib/labels";
import { useMemberAvatarSrc, type Member } from "@/lib/profile";

/** The agent's name as people say it: "Claude Code", "Product agent". */
export function agentName(handle: string): string {
  const coding = AGENT_LABELS[handle as keyof typeof AGENT_LABELS];
  if (coding) return coding;
  if (handle === "pm" || handle === "project-manager") return "Project manager";
  return `${handle.charAt(0).toUpperCase()}${handle.slice(1)} agent`;
}

function personName(id: string | null | undefined, members: MemberMap): string {
  if (!id) return "Someone";
  return members.get(id)?.display_name ?? "A former member";
}

function dayLabel(iso: string): string {
  const day = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (day.toDateString() === today.toDateString()) return "Today";
  if (day.toDateString() === yesterday.toDateString()) return "Yesterday";
  return day.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

/** What happened, as one sentence with links to the issue or document. */
function describe(item: ActivityItem, members: MemberMap, base: string): { text: ReactNode; detail?: ReactNode } {
  const issue = item.issue_key && (
    <Link href={`${base}/board?issue=${item.issue_key}`} className="font-medium hover:underline">
      <span className="text-muted-foreground font-mono text-xs">{item.issue_key}</span> {item.issue_title}
    </Link>
  );
  const doc = item.path && (
    <Link href={`${base}/knowledge?file=${encodeURIComponent(item.path)}`} className="font-mono text-xs hover:underline">
      {item.path}
    </Link>
  );
  switch (item.kind) {
    case "issue.created":
      return { text: <>created {issue}</> };
    case "issue.claimed":
      return { text: <>started {issue}</> };
    case "issue.commented":
      return { text: <>commented on {issue}</>, detail: item.body };
    case "issue.updated": {
      const changes = Object.entries(item.changes ?? {}) as [string, [unknown, unknown]][];
      const status = changes.find(([field]) => field === "status");
      if (status && changes.length === 1) {
        return {
          text: (
            <>
              moved {issue} from {show("status", status[1][0], members)} to {show("status", status[1][1], members)}
            </>
          ),
        };
      }
      const fields = [...new Set(changes.map(([field]) => FIELD_LABELS[field] ?? field.replace(/_/g, " ")))];
      return {
        text: (
          <>
            changed {fields.join(", ") || "details"} on {issue}
          </>
        ),
      };
    }
    case "document.changed":
    case "document.deleted": {
      const who = [
        item.instructed_by_id && `asked by ${personName(item.instructed_by_id, members)}`,
        item.approved_by_id && `approved by ${personName(item.approved_by_id, members)}`,
      ].filter(Boolean);
      return {
        text: (
          <>
            {item.kind === "document.deleted" ? "deleted" : "changed"} {doc}
            {item.version ? <span className="text-muted-foreground"> · v{item.version}</span> : null}
          </>
        ),
        detail: [item.body, who.join(", ")].filter(Boolean).join(" · ") || undefined,
      };
    }
    case "run.started":
      return {
        text: item.run_kind === "briefing" ? <>asked for a briefing</> : <>asked the agents</>,
        detail: item.run_kind === "briefing" ? undefined : item.body,
      };
    case "approval.decided":
      return {
        text: (
          <>
            {item.decision === "approved" ? "approved" : "rejected"} an agent&apos;s change
            {item.target ? <span className="font-mono text-xs"> {item.target}</span> : null}
          </>
        ),
        detail: item.reason ?? undefined,
      };
    default:
      return { text: <>did something</> };
  }
}

function ActorPhoto({ member }: { member: Member | undefined }) {
  const photo = useMemberAvatarSrc(member);
  return photo ? <AvatarImage src={photo} alt="" className="rounded-lg object-cover" /> : null;
}

/** A feed of what people and agents did, grouped by day; agents get a bot tile, people their initials. */
export function ActivityFeed({
  items,
  members,
  workspaceSlug,
  compact = false,
  showProject = false,
}: {
  items: ActivityItem[];
  members: MemberMap;
  /** For links to each item's issue or document, in its project. */
  workspaceSlug: string;
  compact?: boolean;
  /** Name the project on each item (feeds across projects). */
  showProject?: boolean;
}) {
  let lastDay = "";
  return (
    <ol className="flex flex-col">
      {items.map((item, index) => {
        const day = dayLabel(item.at);
        const heading = !compact && day !== lastDay;
        lastDay = day;
        const agent = item.actor_agent;
        const actor = agent ? agentName(agent) : personName(item.actor_user_id, members);
        const { text, detail } = describe(item, members, `/w/${workspaceSlug}/p/${item.project_key}`);
        return (
          <li key={`${item.at}-${index}`} className="flex flex-col">
            {heading && <h3 className="text-muted-foreground pt-5 pb-1 text-[11px] font-semibold tracking-wider uppercase first:pt-0">{day}</h3>}
            <div className="flex items-start gap-3 border-b py-3 last:border-b-0">
              <Avatar className="size-7 rounded-lg">
                {!agent && item.actor_user_id && <ActorPhoto member={members.get(item.actor_user_id)} />}
                <AvatarFallback className={agent ? "bg-brand-muted text-brand-muted-foreground rounded-lg" : "rounded-lg text-[10px]"}>
                  {agent ? <BotIcon className="size-4" /> : initials(actor)}
                </AvatarFallback>
              </Avatar>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-sm">
                <p className="min-w-0">
                  <span className="font-semibold">{actor}</span> <span className="text-muted-foreground">{text}</span>
                </p>
                {detail && <p className="text-muted-foreground line-clamp-2 text-xs">{detail}</p>}
                {showProject && (
                  <Link href={`/w/${workspaceSlug}/p/${item.project_key}`} className="text-muted-foreground flex items-center gap-1.5 text-xs hover:underline">
                    <ProjectTile projectKey={item.project_key} className="size-3.5 text-[7px]" />
                    {item.project_name}
                  </Link>
                )}
              </div>
              <time dateTime={item.at} className="text-muted-foreground shrink-0 text-xs" title={new Date(item.at).toLocaleString()}>
                {timeAgo(item.at)}
              </time>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
