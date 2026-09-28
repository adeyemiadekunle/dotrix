"use client"

import * as React from "react"
import { ArrowDownIcon } from "lucide-react"
import { cn } from "@pmagent/ui/lib/utils"
import { Button } from "@pmagent/ui/components/button"

const NEAR_BOTTOM_PX = 48

/**
 * A scrolling area for a conversation or a live log. While you're at the bottom it follows
 * new content (including text that grows as it streams); scroll up to read and it stays put,
 * offering "Jump to latest" instead. Change `followKey` (e.g. the conversation's id) to jump
 * back to the bottom.
 */
function ChatScroller({
  children,
  className,
  contentClassName,
  followKey,
  jumpLabel = "Jump to latest",
}: {
  children: React.ReactNode
  className?: string
  contentClassName?: string
  followKey?: unknown
  jumpLabel?: string
}) {
  const viewport = React.useRef<HTMLDivElement>(null)
  const content = React.useRef<HTMLDivElement>(null)
  const pinned = React.useRef(true)
  const [showJump, setShowJump] = React.useState(false)

  const scrollToBottom = React.useCallback((behavior: ScrollBehavior = "auto") => {
    const el = viewport.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior })
  }, [])

  React.useEffect(() => {
    const el = viewport.current
    const inner = content.current
    if (!el || !inner) return
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX
      pinned.current = atBottom
      setShowJump(!atBottom)
    }
    el.addEventListener("scroll", onScroll, { passive: true })
    // Content grew (a message arrived, streamed text got longer, an image loaded).
    const observer = new ResizeObserver(() => {
      if (pinned.current) scrollToBottom()
      else setShowJump(true)
    })
    observer.observe(inner)
    return () => {
      el.removeEventListener("scroll", onScroll)
      observer.disconnect()
    }
  }, [scrollToBottom])

  React.useEffect(() => {
    pinned.current = true
    setShowJump(false)
    scrollToBottom()
  }, [followKey, scrollToBottom])

  return (
    <div data-slot="chat-scroller" className={cn("relative min-h-0 flex-1", className)}>
      <div ref={viewport} className="h-full overflow-y-auto overscroll-contain">
        <div ref={content} className={contentClassName}>
          {children}
        </div>
      </div>
      {showJump && (
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full shadow-md"
          onClick={() => {
            pinned.current = true
            setShowJump(false)
            scrollToBottom("smooth")
          }}
        >
          <ArrowDownIcon />
          {jumpLabel}
        </Button>
      )}
    </div>
  )
}

export { ChatScroller }
