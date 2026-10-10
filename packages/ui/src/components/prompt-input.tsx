"use client";

import * as React from "react";
import { ArrowUpIcon, Loader2Icon, SquareIcon } from "lucide-react";
import { Button } from "@dotrix/ui/components/button";
import { Textarea } from "@dotrix/ui/components/textarea";

/**
 * - `ready`: can send (when there's text)
 * - `sending`: the message is on its way
 * - `working`: the agent is working; the button stops it (if `onStop` is given)
 * - `stopping`: a stop was asked for
 * - `waiting`: nothing to do until something else happens (e.g. approvals); input is disabled
 */
type PromptStatus = "ready" | "sending" | "working" | "stopping" | "waiting";

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
  start,
  footer,
  className,
  inputRef,
  onKeyDown,
  above,
}: {
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: (text: string) => void;
  onStop?: () => void;
  status?: PromptStatus;
  placeholder?: string;
  hint?: React.ReactNode;
  label?: string;
  maxLength?: number;
  /** Controls before the text, e.g. a + menu and the chips it sets. */
  start?: React.ReactNode;
  /** A row under the box, e.g. the + menu, its chips, and the model. */
  footer?: React.ReactNode;
  className?: string;
  inputRef?: React.Ref<HTMLTextAreaElement>;
  /** Runs first; return true when it handled the key (e.g. a suggestion list), so Enter doesn't send. */
  onKeyDown?: (event: React.KeyboardEvent<HTMLTextAreaElement>) => boolean | void;
  /** Shown just above the box, e.g. suggestions for what's being typed. */
  above?: React.ReactNode;
}) {
  const ready = status === "ready";
  const stoppable = (status === "working" || status === "stopping") && onStop !== undefined;

  function submit() {
    const text = value.trim();
    if (ready && text) onSubmit(text);
  }

  return (
    <form
      data-slot="prompt-input"
      className={className}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="bg-background focus-within:ring-ring/50 relative flex items-end gap-2 rounded-xl border p-1.5 pl-2 shadow-xs focus-within:ring-2">
        {above}
        {start && <div className="flex shrink-0 items-center gap-1 self-end pb-0.5">{start}</div>}
        <Textarea
          ref={inputRef}
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (onKeyDown?.(event)) return;
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={placeholder}
          disabled={!ready && status !== "sending"}
          readOnly={status === "sending"}
          rows={1}
          maxLength={maxLength}
          aria-label={label}
          className="max-h-40 min-h-8 flex-1 resize-none border-0 bg-transparent px-1.5 py-1 shadow-none focus-visible:ring-0 dark:bg-transparent"
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
          <Button type="submit" size="icon" className="size-8 shrink-0 rounded-lg" disabled={!ready || !value.trim()} aria-label="Send" title="Send">
            {status === "sending" ? <Loader2Icon className="animate-spin" /> : <ArrowUpIcon />}
          </Button>
        )}
      </div>
      {footer && <div className="mt-1.5 flex min-w-0 items-center gap-1.5">{footer}</div>}
      {hint && <p className="text-muted-foreground mt-1.5 text-[11px]">{hint}</p>}
    </form>
  );
}

export { PromptInput, type PromptStatus };
