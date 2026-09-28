"use client"

import * as React from "react"
import { ArrowUpIcon, Loader2Icon, SquareIcon } from "lucide-react"
import { Button } from "@pmagent/ui/components/button"
import { Textarea } from "@pmagent/ui/components/textarea"

/**
 * - `ready`: can send (when there's text)
 * - `sending`: the message is on its way
 * - `working`: the agent is working; the button stops it (if `onStop` is given)
 * - `stopping`: a stop was asked for
 * - `waiting`: nothing to do until something else happens (e.g. approvals); input is disabled
 */
type PromptStatus = "ready" | "sending" | "working" | "stopping" | "waiting"

/**
 * The message box for talking to an agent. Grows with its text; Enter sends, Shift+Enter
 * starts a new line (and Enter while an input method is composing never sends). While the
 * agent works, the send button becomes Stop.
 */
function PromptInput({
  value,
  onValueChange,
  onSubmit,
  onStop,
  status = "ready",
  placeholder,
  hint,
  label = "Message",
  maxLength = 20_000,
  className,
}: {
  value: string
  onValueChange: (value: string) => void
  onSubmit: (text: string) => void
  onStop?: () => void
  status?: PromptStatus
  placeholder?: string
  hint?: React.ReactNode
  label?: string
  maxLength?: number
  className?: string
}) {
  const ready = status === "ready"
  const stoppable = (status === "working" || status === "stopping") && onStop !== undefined

  function submit() {
    const text = value.trim()
    if (ready && text) onSubmit(text)
  }

  return (
    <form
      data-slot="prompt-input"
      className={className}
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <div className="bg-background focus-within:ring-ring/50 flex items-end gap-2 rounded-xl border p-2 focus-within:ring-2">
        <Textarea
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              submit()
            }
          }}
          placeholder={placeholder}
          disabled={!ready && status !== "sending"}
          readOnly={status === "sending"}
          rows={1}
          maxLength={maxLength}
          aria-label={label}
          className="max-h-40 min-h-9 flex-1 resize-none border-0 bg-transparent p-1.5 shadow-none focus-visible:ring-0 dark:bg-transparent"
        />
        {stoppable ? (
          <Button
            type="button"
            size="icon"
            variant="secondary"
            className="size-8 shrink-0 rounded-lg"
            disabled={status === "stopping"}
            onClick={onStop}
            aria-label="Stop"
            title="Stop"
          >
            {status === "stopping" ? <Loader2Icon className="animate-spin" /> : <SquareIcon className="fill-current" />}
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            className="size-8 shrink-0 rounded-lg"
            disabled={!ready || !value.trim()}
            aria-label="Send"
            title="Send"
          >
            {status === "sending" ? <Loader2Icon className="animate-spin" /> : <ArrowUpIcon />}
          </Button>
        )}
      </div>
      {hint && <p className="text-muted-foreground mt-1.5 text-[11px]">{hint}</p>}
    </form>
  )
}

export { PromptInput, type PromptStatus }
