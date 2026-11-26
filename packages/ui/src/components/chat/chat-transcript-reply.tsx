import type { ReactNode } from "react";

import { ChatMessageBubble } from "./chat-message-bubble";
import { ChatMessage, type ChatMessageProps } from "./chat-message";
import { ChatMessageText } from "./chat-message-text";

type ChatTranscriptReplyProps = Omit<
  ChatMessageProps,
  "side" | "bubble" | "children" | "actions" | "animateEntrance" | "highlighted" | "onAnimationComplete"
> & {
  body?: ReactNode;
  beforeBody?: ReactNode;
  children?: ReactNode;
};

/** A full-width reply with space for traces above the bubble and cards below it. */
export function ChatTranscriptReply({ body, beforeBody, children, bubbleProps, ...props }: ChatTranscriptReplyProps) {
  return (
    <ChatMessage side="incoming" bubble={false} {...props}>
      <div className="grid min-w-0 gap-2">
        {beforeBody}
        {body != null && (
          <ChatMessageBubble side="incoming" {...bubbleProps}>
            {typeof body === "string" ? <ChatMessageText text={body} /> : body}
          </ChatMessageBubble>
        )}
        {children}
      </div>
    </ChatMessage>
  );
}
