// Dev-only gallery for the coss chat components ported into @dotrix/ui.
// Reach it at /dev/chat-ui — not linked from the app.
import { ChatCollapsibleMessage } from "@dotrix/ui/components/chat/chat-collapsible-message";
import { ChatConversation } from "@dotrix/ui/components/chat/chat-conversation";
import { ChatDatePill } from "@dotrix/ui/components/chat/chat-date-pill";
import { ChatDeliveryIndicator } from "@dotrix/ui/components/chat/chat-delivery-indicator";
import { ChatEmptyState, ChatLoadingState, ChatStatusBar } from "@dotrix/ui/components/chat/chat-states";
import { ChatMessage } from "@dotrix/ui/components/chat/chat-message";
import { ChatMessageActionToolbar } from "@dotrix/ui/components/chat/chat-message-actions";
import { ChatMessageText } from "@dotrix/ui/components/chat/chat-message-text";
import { ChatReactionChip } from "@dotrix/ui/components/chat/chat-reaction-chip";
import { ChatReactionPicker } from "@dotrix/ui/components/chat/chat-reaction-picker";
import { ChatReplyReference } from "@dotrix/ui/components/chat/chat-reply-reference";
import { ChatTranscriptReply } from "@dotrix/ui/components/chat/chat-transcript-reply";
import { ChatTypingIndicator } from "@dotrix/ui/components/chat/chat-typing-indicator";
import { ChatUnreadDivider } from "@dotrix/ui/components/chat/chat-unread-divider";
import { useChatScroll } from "@dotrix/ui/components/chat/hooks/use-chat-scroll";
import { MenuItem } from "@dotrix/ui/components/chat/ui/menu";
import { MessageSquareIcon } from "lucide-react";

const LONG_TEXT = `Here's the migration plan I put together for the settings screen.

First, the form primitives: Field and InputGroup give us labelled inputs with consistent spacing and error slots, which removes about forty lines of hand-rolled markup per form. The settings page has eleven of those.

Second, Switch replaces the custom toggle — it's the same ui-sdk primitive underneath but styled to match, with proper keyboard support and a visible focus ring.

Third, the segmented control for the appearance picker. Right now it's three radio cards that don't behave like a group on mobile.

One thing to flag: the theme tokens are close but not identical. coss uses a slightly warmer neutral scale, so I'd keep our --surface-2/--surface-3 mapping rather than adopt theirs wholesale. The component APIs are what we're taking, not the palette.

Want me to start with the switch migration as a pilot?`;

function Avatar({ children }: { children: string }) {
  return <span className="flex size-7 items-center justify-center rounded-full bg-primary/15 text-[11px] font-semibold text-primary">{children}</span>;
}

const REACTION_OPTIONS = [
  { emoji: "\u{1F44D}", label: "Thumbs up" },
  { emoji: "\u{1F680}", label: "Ship it" },
  { emoji: "\u{1F440}", label: "Watching" },
  { emoji: "\u{1F64C}", label: "Meh" },
];

function MessageActions() {
  return (
    <ChatMessageActionToolbar
      side="incoming"
      toolbarLabel="Message actions"
      reactionPicker={(toolbarRef) => (
        <ChatReactionPicker
          inToolbar
          options={REACTION_OPTIONS}
          selectedEmojis={["\u{1F44D}"]}
          triggerLabel="React"
          triggerTooltip="React"
          popupLabel="Choose a reaction"
          popupAnchor={toolbarRef}
          onSelect={() => {}}
        />
      )}
      onReply={() => {}}
      replyLabel="Reply"
      replyTooltip="Reply"
      menuChildren={
        <>
          <MenuItem>Copy text</MenuItem>
          <MenuItem>Copy link</MenuItem>
          <MenuItem variant="destructive">Delete</MenuItem>
        </>
      }
      moreLabel="More actions"
      moreTooltip="More"
    />
  );
}

export default function ChatUiLab() {
  const scroll = useChatScroll({ itemCount: 9 });

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="flex h-12 shrink-0 items-center border-border border-b px-4 text-sm font-medium">
        chat/ui lab <span className="ml-2 text-muted-foreground text-xs">@dotrix/ui/components/chat</span>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 w-full max-w-3xl flex-1 flex-col border-border border-r">
          <ChatConversation scroll={scroll} label="Demo conversation" jumpLabel="Jump to latest" contentClassName="flex flex-col gap-5 py-4">
            <ChatDatePill className="mx-auto">Today</ChatDatePill>

            <ChatMessage side="incoming" author="Nova" avatar={<Avatar>N</Avatar>} actions={<MessageActions />}>
              Morning! I pulled the thread history — the settings rework is the biggest remaining chunk. Want the breakdown?
            </ChatMessage>

            <ChatUnreadDivider>New messages</ChatUnreadDivider>

            <ChatMessage
              side="incoming"
              author="Nova"
              avatar={<Avatar>N</Avatar>}
              grouped
              actions={<MessageActions />}
              reactions={
                <>
                  <ChatReactionChip emoji="\u{1F44D}" count={2} selected label="Thumbs up, 2 reactors" onClick={() => {}} />
                  <ChatReactionChip emoji="\u{1F680}" count={1} selected={false} label="Rocket, 1 reactor" onClick={() => {}} />
                </>
              }
            >
              <ChatCollapsibleMessage text={LONG_TEXT} side="incoming" showMoreLabel="Show more" showLessLabel="Show less" />
            </ChatMessage>

            <ChatMessage
              side="outgoing"
              footer={
                <span className="flex items-center gap-1">
                  9:41 <ChatDeliveryIndicator status="read" label="Read" />
                </span>
              }
            >
              Yes please — start with the switch pilot.
            </ChatMessage>

            <ChatTranscriptReply
              author="Nova"
              avatar={<Avatar>N</Avatar>}
              beforeBody={<ChatReplyReference author="You" preview="Yes please — start with the switch pilot." />}
              body={<ChatMessageText text="On it. I'll open a branch and keep the token mapping identical so nothing else shifts." />}
            />

            <ChatTypingIndicator label="Nova is typing" visible />
          </ChatConversation>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-8 overflow-y-auto p-6">
          <section>
            <h2 className="mb-3 text-muted-foreground text-xs font-medium uppercase tracking-wide">States</h2>
            <ChatEmptyState
              title="No conversations yet"
              description="Start a chat with Nova to plan, research, or hand off to Kai."
              icon={<MessageSquareIcon className="size-4" />}
            />
          </section>
          <section>
            <h2 className="mb-3 text-muted-foreground text-xs font-medium uppercase tracking-wide">Loading</h2>
            <ChatLoadingState label="Loading messages" />
          </section>
          <section>
            <h2 className="mb-3 text-muted-foreground text-xs font-medium uppercase tracking-wide">Status bar</h2>
            <ChatStatusBar
              title="Kai is working"
              description="PR #412 · checks running"
              action={
                <button className="btn btn-secondary btn-sm" type="button">
                  Open in Code
                </button>
              }
            />
          </section>
        </div>
      </div>
    </div>
  );
}
