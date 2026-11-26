import { Button } from "@dotrix/ui/components/button";
import { Input } from "@dotrix/ui/components/input";
import { MessageSquareIcon } from "lucide-react";
import { useRef, useState } from "react";

import { ChatCollapsibleMessage } from "./chat-collapsible-message";
import { ChatConversation } from "./chat-conversation";
import { ChatDatePill } from "./chat-date-pill";
import { ChatDeliveryIndicator } from "./chat-delivery-indicator";
import { ChatMessageActionToolbar } from "./chat-message-actions";
import { ChatMessage } from "./chat-message";
import { ChatReactionChip } from "./chat-reaction-chip";
import { ChatReactionPicker } from "./chat-reaction-picker";
import { ChatReplyReference } from "./chat-reply-reference";
import { ChatEmptyState, ChatLoadingState, ChatStatusBar } from "./chat-states";
import { ChatTypingIndicator } from "./chat-typing-indicator";
import { ChatUnreadDivider } from "./chat-unread-divider";
import { useChatScroll } from "./hooks/use-chat-scroll";
import { MenuItem } from "./ui/menu";

const preview = "The launch checklist is ready for review.";
const brief = `${preview}

I grouped the remaining work into three items. First, verify keyboard navigation and focus in Chat and Code. Then check that the demo loads without signing in. Finally, review the admin run and failure views with a mix of successful, queued, and failed runs.

Once those checks pass, Kai can prepare a pull request with the test results. The team can review the evidence and decide when to merge.`;
const reactions = [
  { emoji: "👍", label: "Thumbs up" },
  { emoji: "🚀", label: "Rocket" },
  { emoji: "👀", label: "Eyes" },
];

export function ChatShowcase() {
  const [selected, setSelected] = useState<string[]>([]);
  const [replies, setReplies] = useState<{ text: string; quoted: boolean }[]>([]);
  const [draft, setDraft] = useState("");
  const [quoting, setQuoting] = useState(false);
  const source = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const scroll = useChatScroll({ itemCount: 5 + replies.length });

  function toggleReaction(emoji: string) {
    setSelected((current) => (current.includes(emoji) ? current.filter((item) => item !== emoji) : [...current, emoji]));
  }

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <section aria-label="Interactive sample chat" className="flex min-w-0 flex-col rounded-xl border border-border bg-card">
        <div className="border-b border-border px-4 py-3 font-medium">Launch checklist</div>
        <div className="flex h-96 min-h-0 flex-col">
          <ChatConversation scroll={scroll} label="Sample conversation" jumpLabel="Jump to latest" contentClassName="flex flex-col gap-4 py-4">
            <ChatDatePill className="mx-auto">Today</ChatDatePill>
            <ChatMessage side="outgoing" footer={<ChatDeliveryIndicator status="read" label="Read" />}>
              What should we verify before sharing the demo?
            </ChatMessage>
            <ChatUnreadDivider>New messages</ChatUnreadDivider>
            <div ref={source} tabIndex={-1}>
              <ChatMessage
                side="incoming"
                author="Nova"
                avatar={<span className="grid size-7 place-items-center rounded-full bg-primary/15 text-xs font-semibold text-primary">N</span>}
                actions={
                  <ChatMessageActionToolbar
                    side="incoming"
                    toolbarLabel="Message actions"
                    reactionPicker={(toolbarRef) => (
                      <ChatReactionPicker
                        inToolbar
                        options={reactions}
                        selectedEmojis={selected}
                        triggerLabel="React"
                        triggerTooltip="React"
                        popupLabel="Choose a reaction"
                        popupAnchor={toolbarRef}
                        onSelect={toggleReaction}
                      />
                    )}
                    onReply={() => {
                      setQuoting(true);
                      input.current?.focus();
                    }}
                    replyLabel="Reply"
                    replyTooltip="Reply"
                    menuChildren={<MenuItem onSelect={() => setSelected([])}>Clear sample reactions</MenuItem>}
                    moreLabel="More actions"
                    moreTooltip="More actions"
                  />
                }
                reactions={reactions
                  .filter(({ emoji }) => selected.includes(emoji))
                  .map(({ emoji, label }) => (
                    <ChatReactionChip key={emoji} emoji={emoji} count={1} selected label={`${label}, 1 reaction`} onClick={() => toggleReaction(emoji)} />
                  ))}
              >
                <ChatCollapsibleMessage text={brief} side="incoming" maxPreviewLength={150} showMoreLabel="Show more" showLessLabel="Show less" />
              </ChatMessage>
            </div>
            {replies.map(({ text, quoted }, index) => (
              <ChatMessage key={index} side="outgoing">
                {quoted && <ChatReplyReference author="Nova" preview={preview} onClick={() => source.current?.focus()} />}
                <p className="break-words whitespace-pre-wrap">{text}</p>
              </ChatMessage>
            ))}
            <ChatTypingIndicator label="Nova is typing" visible />
          </ChatConversation>
        </div>
        <form
          className="grid gap-2 border-t border-border p-3"
          onSubmit={(event) => {
            event.preventDefault();
            const text = draft.trim();
            if (!text) return;
            setReplies((current) => [...current, { text, quoted: quoting }]);
            setDraft("");
            setQuoting(false);
          }}
        >
          {quoting && (
            <div className="flex items-center justify-between gap-2 text-sm">
              <span>Replying to Nova</span>
              <Button type="button" variant="ghost" size="sm" onClick={() => setQuoting(false)}>
                Cancel reply
              </Button>
            </div>
          )}
          <div className="flex gap-2">
            <Input ref={input} value={draft} onChange={(event) => setDraft(event.target.value)} aria-label="Sample reply" placeholder="Write a sample reply" />
            <Button type="submit" disabled={!draft.trim()}>
              Send
            </Button>
          </div>
        </form>
      </section>

      <section aria-label="Sample chat states" className="grid content-start gap-4">
        <div className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-medium">Empty state</h2>
          <ChatEmptyState title="No conversations yet" description="Start a chat to plan or research." icon={<MessageSquareIcon className="size-4" />} />
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-medium">Loading state</h2>
          <ChatLoadingState label="Loading messages" />
        </div>
        <ChatStatusBar title="Kai is working" description="Sample run · checks pending" />
      </section>
    </div>
  );
}
