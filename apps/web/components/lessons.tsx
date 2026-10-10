import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { Textarea } from "@dotrix/ui/components/textarea";
import { Link } from "@/lib/navigation";
import { useState } from "react";

import { timeAgo } from "@/components/issues/issue-activity";
import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import type { Scope } from "@/lib/issues";
import { useDecideLesson, useLessons, type Lesson } from "@/lib/lessons";

/** Project settings → Lessons (owners and admins): what rejections and dismissals could teach the agents. */
export function Lessons({ scope, knowledgeHref }: { scope: Scope; knowledgeHref: string }) {
  const lessons = useLessons(scope, true);
  const proposed = lessons.data?.filter((l) => l.status === "proposed") ?? [];
  const decided = lessons.data?.filter((l) => l.status !== "proposed").slice(0, 5) ?? [];
  return (
    <SettingsSection id="lessons" stacked>
      <SettingsHeader>
        <SettingsTitle>Lessons</SettingsTitle>
        <SettingsDescription>
          When you reject an agent&apos;s change or dismiss what it found, with a reason, the agent could learn from it.
          Accept a lesson (in your words if you like) and it joins that agent&apos;s rules in{" "}
          <Link href={knowledgeHref} className="underline underline-offset-4">
            agent-rules/lessons/
          </Link>
          , where you can edit or remove it.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="p-0">
        {!lessons.data ? (
          <Skeleton className="m-5 h-20" />
        ) : proposed.length === 0 && decided.length === 0 ? (
          <p className="text-muted-foreground p-5 text-sm">
            Nothing to learn yet. Give a reason when you reject a change or dismiss a finding.
          </p>
        ) : (
          <ul className="divide-y" aria-label="Lessons">
            {proposed.map((l) => (
              <ProposedLesson key={l.id} lesson={l} scope={scope} />
            ))}
            {decided.map((l) => (
              <li key={l.id} className="flex flex-wrap items-center gap-2 p-4 text-sm">
                <Badge variant="outline">@{l.agent}</Badge>
                <span className="text-muted-foreground min-w-0 flex-1 truncate">{l.text}</span>
                <Badge variant={l.status === "accepted" ? "secondary" : "outline"}>
                  {l.status === "accepted" ? "Accepted" : "Declined"}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </SettingsContent>
    </SettingsSection>
  );
}

function ProposedLesson({ lesson, scope }: { lesson: Lesson; scope: Scope }) {
  const [text, setText] = useState(lesson.text);
  const decide = useDecideLesson(scope);
  return (
    <li className="grid gap-2 p-4 text-sm">
      <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="outline">@{lesson.agent}</Badge>
        From a {lesson.source === "rejection" ? "rejected change" : "dismissed result"} {timeAgo(lesson.created_at)}
      </p>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={600}
        rows={2}
        aria-label="The lesson"
      />
      <div className="flex justify-end gap-2">
        <Button
          size="sm"
          variant="ghost"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ id: lesson.id, accept: false })}
        >
          Decline
        </Button>
        <Button
          size="sm"
          disabled={decide.isPending || !text.trim()}
          onClick={() => decide.mutate({ id: lesson.id, accept: true, text: text.trim() })}
        >
          Accept
        </Button>
      </div>
    </li>
  );
}
