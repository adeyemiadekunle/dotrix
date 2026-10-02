"use client";

import type { Schemas } from "@pmagent/api-client";
import { Avatar, AvatarFallback, AvatarImage } from "@pmagent/ui/components/avatar";
import { Textarea } from "@pmagent/ui/components/textarea";
import { BotIcon } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";

import { SubmitButton } from "@/components/form";
import { Markdown } from "@/components/markdown";
import { useMentions } from "@/components/mentions";
import { initials } from "@/lib/labels";
import { useMemberAvatarSrc, type Member } from "@/lib/profile";

import { AGENT_LABELS, PRIORITY_META, STATUS_META, TYPE_META, type MemberMap } from "./meta";

type Event = Schemas["IssueEventRead"];

export const FIELD_LABELS: Record<string, string> = {
  assignee_user_id: "assignee",
  assignee_agent: "assignee",
  depends_on: "dependencies",
  due: "due date",
};

export function timeAgo(iso: string): string {
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return "just now";
}

function authorOf(event: Event, members: MemberMap): { name: string; agent: boolean; member?: Member } {
  if (event.author_agent) {
    const label = AGENT_LABELS[event.author_agent as keyof typeof AGENT_LABELS];
    return { name: label ?? event.author_agent, agent: true };
  }
  if (event.author_user_id) {
    const member = members.get(event.author_user_id);
    return { name: member?.display_name ?? "Former member", agent: false, member };
  }
  return { name: "Someone", agent: false };
}

export function show(field: string, value: unknown, members: MemberMap): string {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) return "none";
  if (field === "status") return STATUS_META[value as keyof typeof STATUS_META]?.label ?? String(value);
  if (field === "priority") return PRIORITY_META[value as keyof typeof PRIORITY_META]?.label ?? String(value);
  if (field === "type") return TYPE_META[value as keyof typeof TYPE_META]?.label ?? String(value);
  if (field === "assignee_user_id") return members.get(String(value))?.display_name ?? "a former member";
  if (field === "assignee_agent") return AGENT_LABELS[value as keyof typeof AGENT_LABELS] ?? String(value);
  if (Array.isArray(value)) return value.join(", ");
  const text = String(value);
  return text.length > 60 ? `${text.slice(0, 60)}…` : text;
}

function describe(event: Event, members: MemberMap): string[] {
  if (event.kind === "created") return ["created the issue"];
  if (event.kind === "claimed") return ["claimed the issue"];
  if (event.kind === "commented") return [];
  const lines = Object.entries(event.changes).map(([field, change]) => {
    const [before, after] = change as [unknown, unknown];
    const label = FIELD_LABELS[field] ?? field.replaceAll("_", " ");
    if (field === "description") return "edited the description";
    return `changed ${label} from ${show(field, before, members)} to ${show(field, after, members)}`;
  });
  return lines.length ? lines : ["updated the issue"];
}

function EventRow({ event, members }: { event: Event; members: MemberMap }) {
  const author = authorOf(event, members);
  const lines = describe(event, members);
  const photo = useMemberAvatarSrc(author.member);
  return (
    <li className="flex gap-3">
      <Avatar className="mt-0.5 size-6">
        {photo && <AvatarImage src={photo} alt="" className="object-cover" />}
        <AvatarFallback className={author.agent ? "bg-brand text-brand-foreground" : "text-[10px]"}>
          {author.agent ? <BotIcon className="size-3.5" /> : initials(author.name)}
        </AvatarFallback>
      </Avatar>
      <div className="grid min-w-0 flex-1 gap-1 text-sm">
        <p>
          <span className="font-medium">{author.name}</span>{" "}
          <span className="text-muted-foreground">
            {event.kind === "commented" ? "commented" : lines[0]} · {timeAgo(event.created_at)}
          </span>
        </p>
        {lines.slice(1).map((line) => (
          <p key={line} className="text-muted-foreground">
            {line}
          </p>
        ))}
        {event.body && (
          <div className={event.kind === "commented" ? "rounded-lg border px-3 py-2" : ""}>
            <Markdown>{event.body}</Markdown>
          </div>
        )}
      </div>
    </li>
  );
}

export function IssueActivity({
  log,
  members,
  mentionable = [],
  canComment,
  onComment,
  commenting,
}: {
  log: Event[];
  members: MemberMap;
  /** Whom a comment may @mention: the people who can see the project. */
  mentionable?: Member[];
  canComment: boolean;
  onComment: (body: string, mentions: string[]) => Promise<unknown>;
  commenting: boolean;
}) {
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const mentions = useMentions({ people: mentionable, value: draft, onValueChange: setDraft, inputRef: input });

  async function submit(event: FormEvent) {
    event.preventDefault();
    const body = draft.trim();
    if (!body) return;
    await onComment(body, mentions.mentioned(body));
    setDraft("");
    mentions.reset();
  }

  return (
    <section className="grid gap-4">
      <h3 className="text-sm font-medium">Activity</h3>
      <ol className="grid gap-4">
        {log.map((event, i) => (
          <EventRow key={`${event.created_at}-${i}`} event={event} members={members} />
        ))}
      </ol>
      {canComment && (
        <form
          onSubmit={submit}
          className="focus-within:ring-ring/50 bg-background relative grid gap-1 rounded-xl border p-2 shadow-xs focus-within:ring-2"
        >
          {mentions.list}
          <Textarea
            ref={input}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              mentions.track(e.target.value, e.target.selectionStart);
            }}
            onKeyDown={(e) => {
              if (mentions.onKeyDown(e)) return;
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit(e);
            }}
            onBlur={() => mentions.track(draft, null)}
            aria-label="Comment"
            placeholder="Add a comment; @ to mention someone (Markdown supported)"
            rows={2}
            maxLength={20_000}
            className="min-h-14 resize-none border-0 bg-transparent px-1.5 py-1 shadow-none focus-visible:ring-0 dark:bg-transparent"
          />
          <div className="flex items-center justify-between pl-1.5">
            <span className="text-muted-foreground text-xs">Ctrl+Enter to send</span>
            <SubmitButton pending={commenting} size="sm" disabled={commenting || !draft.trim()}>
              Comment
            </SubmitButton>
          </div>
        </form>
      )}
    </section>
  );
}
