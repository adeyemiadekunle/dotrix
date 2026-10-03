"use client";

import { Button } from "@pmagent/ui/components/button";
import { Checkbox } from "@pmagent/ui/components/checkbox";
import { ChatBubble, ChatMessage, ChatMessageMeta, ChatNotice } from "@pmagent/ui/components/chat-message";
import { ChatScroller } from "@pmagent/ui/components/chat-scroller";
import { PromptInput, type PromptStatus } from "@pmagent/ui/components/prompt-input";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { BotIcon, CircleAlertIcon, CircleStopIcon, LayersIcon } from "lucide-react";
import { useState } from "react";

import { RunUsage } from "@/components/agent/agent-reply";
import { timeAgo } from "@/components/issues/issue-activity";
import { Markdown } from "@/components/markdown";
import { ProjectTile } from "@/components/project-tile";
import { isActive, wasStopped, type Run } from "@/lib/agent";
import { useCrossStream, useCrossThread, useSendCross, useStopCross } from "@/lib/conversations";

const SUGGESTIONS = [
  "Summarise every project: progress, what's blocked, and what's due this week",
  "Which projects are at risk, and why?",
  "Where do these projects depend on each other, or repeat work?",
];

type ProjectOption = { id: string; key: string; name: string };

function Reply({ run, workspaceId }: { run: Run; workspaceId: string }) {
  const active = isActive(run);
  const live = useCrossStream(workspaceId, run.id, active);
  return (
    <ChatMessage from="agent" avatar={<BotIcon />}>
      <ChatMessageMeta>The agents</ChatMessageMeta>
      {active && live.text && <Markdown>{live.text}</Markdown>}
      {active && (
        <ChatNotice tone="progress">
          {run.status === "queued" ? "Waiting to start…" : live.activity ? `${live.activity}…` : "Reading the projects…"}
        </ChatNotice>
      )}
      {wasStopped(run) && <ChatNotice icon={<CircleStopIcon />}>{run.error}.</ChatNotice>}
      {run.status === "failed" && !wasStopped(run) && (
        <ChatNotice tone="destructive" icon={<CircleAlertIcon />}>
          {run.error ?? "The run failed."}
        </ChatNotice>
      )}
      {run.reply && <Markdown>{run.reply}</Markdown>}
      <RunUsage run={run} />
    </ChatMessage>
  );
}

/**
 * A conversation across projects (or about none): the agents read every project in it and
 * answer, but change nothing; for a change they say which project's conversation to ask in.
 * The projects are picked before the first message and fixed after.
 */
export function CrossConversation({
  workspaceId,
  threadId,
  projects,
  fixedProjects,
  onThread,
  names,
  canChat,
  initialDraft,
}: {
  workspaceId: string;
  threadId: string | null;
  projects: ProjectOption[];
  /** An existing conversation's projects (ids). */
  fixedProjects: string[] | null;
  onThread: (threadId: string) => void;
  names: Map<string, string>;
  canChat: boolean;
  initialDraft?: string;
}) {
  const thread = useCrossThread(workspaceId, threadId);
  const send = useSendCross(workspaceId);
  const stop = useStopCross(workspaceId);
  const [draft, setDraft] = useState(initialDraft ?? "");
  const [chosen, setChosen] = useState<string[]>(() => projects.map((p) => p.id));
  const runs = thread.data ?? [];
  const working = runs.find(isActive);
  const about = fixedProjects ?? chosen;
  const status: PromptStatus = stop.isPending ? "stopping" : working ? "working" : send.isPending ? "sending" : "ready";

  async function submit(text: string) {
    if (status !== "ready" || !text.trim()) return;
    const run = await send
      .mutateAsync({ message: text, thread_id: threadId, project_ids: threadId ? [] : chosen, agent: "auto" })
      .catch(() => null);
    if (run) {
      setDraft("");
      if (run.thread_id !== threadId) onThread(run.thread_id);
    }
  }

  const label = (ids: string[]) =>
    ids.length === 0 ? "no particular project" : projects.filter((p) => ids.includes(p.id)).map((p) => p.key).join(", ");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ChatScroller followKey={threadId} contentClassName="mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)] gap-6 p-4 md:p-6">
        {threadId && thread.isLoading && <Skeleton className="h-24" />}
        {threadId && (
          <p className="text-muted-foreground flex items-center justify-center gap-1.5 text-xs">
            <LayersIcon className="size-3.5" />
            About {label(about)}. Read-only: changes are made in a project&apos;s own conversation.
          </p>
        )}
        {!threadId && (
          <div className="grid gap-4 py-6">
            <div className="grid gap-1 text-center">
              <LayersIcon className="text-brand mx-auto size-6" />
              <p className="font-medium">Ask across projects</p>
              <p className="text-muted-foreground text-sm">
                The agents read every project you pick and answer, comparing and summarising them. Nothing is changed
                here: for a change, they&apos;ll say which project&apos;s conversation to ask in. Only you see this
                conversation.
              </p>
            </div>
            <fieldset className="grid gap-2 rounded-lg border p-3">
              <legend className="px-1 text-sm font-medium">About</legend>
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                {projects.map((p) => (
                  <label key={p.id} className="flex items-center gap-1.5 text-sm">
                    <Checkbox
                      checked={chosen.includes(p.id)}
                      onCheckedChange={(c) => setChosen((ids) => (c === true ? [...ids, p.id] : ids.filter((i) => i !== p.id)))}
                    />
                    <ProjectTile projectKey={p.key} className="size-4 text-[8px]" />
                    {p.name}
                  </label>
                ))}
              </div>
              {chosen.length > 10 && <p className="text-destructive text-xs">Pick 10 projects at most.</p>}
              {chosen.length === 0 && (
                <p className="text-muted-foreground text-xs">None picked: a general question about the workspace.</p>
              )}
            </fieldset>
            {canChat && (
              <div className="grid gap-2">
                {SUGGESTIONS.map((s) => (
                  <Button
                    key={s}
                    variant="outline"
                    size="sm"
                    className="h-auto justify-start py-2 text-left whitespace-normal"
                    disabled={chosen.length > 10}
                    onClick={() => void submit(s)}
                  >
                    {s}
                  </Button>
                ))}
              </div>
            )}
          </div>
        )}
        {runs.map((run) => (
          <div key={run.id} className="grid gap-3">
            <ChatMessage from="user">
              <ChatMessageMeta>
                {(run.requested_by_id && names.get(run.requested_by_id)) || "You"} · {timeAgo(run.created_at)}
              </ChatMessageMeta>
              <ChatBubble>{run.message}</ChatBubble>
            </ChatMessage>
            <Reply run={run} workspaceId={workspaceId} />
          </div>
        ))}
      </ChatScroller>
      {canChat ? (
        <div className="border-t p-4">
          <PromptInput
            className="mx-auto w-full max-w-3xl"
            value={draft}
            onValueChange={setDraft}
            onSubmit={(text) => void submit(text)}
            onStop={working ? () => stop.mutate(working.id) : undefined}
            status={chosen.length > 10 && !threadId ? "waiting" : status}
            label="Message the agents"
            placeholder={working ? "The agents are working…" : threadId ? "Reply" : `Ask about ${label(chosen)}`}
          />
        </div>
      ) : (
        <p className="text-muted-foreground border-t p-4 text-center text-sm">Guests can read, but not chat with the agents.</p>
      )}
    </div>
  );
}
