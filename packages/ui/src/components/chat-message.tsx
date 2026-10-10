import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Loader2Icon } from "lucide-react"
import { cn } from "@dotrix/ui/lib/utils"

/**
 * Building blocks for a conversation, composable like the rest of the kit:
 *
 *   <ChatMessage from="user">
 *     <ChatMessageMeta>Ada · 2 min ago</ChatMessageMeta>
 *     <ChatBubble>What's blocked?</ChatBubble>
 *   </ChatMessage>
 *
 *   <ChatMessage from="agent" avatar={<BotIcon />}>
 *     <ChatNotice tone="progress">Checking the board</ChatNotice>
 *     <Markdown>…</Markdown>
 *   </ChatMessage>
 */
function ChatMessage({
  from,
  avatar,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { from: "user" | "agent"; avatar?: React.ReactNode }) {
  if (from === "user") {
    return (
      <div
        data-slot="chat-message"
        data-from="user"
        className={cn("ml-auto grid max-w-[85%] justify-items-end gap-1", className)}
        {...props}
      >
        {children}
      </div>
    )
  }
  return (
    <div data-slot="chat-message" data-from="agent" className={cn("flex gap-2", className)} {...props}>
      {avatar && <ChatAvatar>{avatar}</ChatAvatar>}
      <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)] content-start gap-3">{children}</div>
    </div>
  )
}

function ChatAvatar({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="chat-avatar"
      className={cn(
        "bg-brand text-brand-foreground mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full [&>svg]:size-3.5",
        className
      )}
      {...props}
    />
  )
}

function ChatBubble({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="chat-bubble"
      className={cn(
        "bg-secondary text-secondary-foreground rounded-2xl rounded-tr-sm px-3 py-2 text-sm break-words whitespace-pre-wrap",
        className
      )}
      {...props}
    />
  )
}

/** Who and when, above a message: "Ada · 2 min ago". */
function ChatMessageMeta({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <p
      data-slot="chat-message-meta"
      className={cn("text-muted-foreground flex items-center gap-1.5 text-xs [&>svg]:size-3.5", className)}
      {...props}
    />
  )
}

const noticeVariants = cva("flex items-start gap-1.5 text-sm [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0", {
  variants: {
    tone: {
      muted: "text-muted-foreground",
      destructive: "text-destructive",
      progress: "text-muted-foreground",
    },
  },
  defaultVariants: { tone: "muted" },
})

/** A status line in a conversation: progress (with a spinner), a note, or an error. */
function ChatNotice({
  tone,
  icon,
  className,
  children,
  ...props
}: React.ComponentProps<"p"> & VariantProps<typeof noticeVariants> & { icon?: React.ReactNode }) {
  return (
    <p
      data-slot="chat-notice"
      role={tone === "progress" ? "status" : undefined}
      aria-live={tone === "progress" ? "polite" : undefined}
      className={cn(noticeVariants({ tone }), className)}
      {...props}
    >
      {icon ?? (tone === "progress" ? <Loader2Icon className="animate-spin" /> : null)}
      <span className="min-w-0">{children}</span>
    </p>
  )
}

export { ChatAvatar, ChatBubble, ChatMessage, ChatMessageMeta, ChatNotice }
