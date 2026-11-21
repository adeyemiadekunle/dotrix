import { ActionButton } from "@dotrix/ui/components/action-button";
import { ChatScroller } from "@dotrix/ui/components/chat-scroller";
import type { PromptStatus } from "@dotrix/ui/components/prompt-input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@dotrix/ui/components/select";
import { useEffect, useImperativeHandle, useRef, useState, type ComponentProps, type KeyboardEvent, type ReactNode, type Ref } from "react";

import { Ic } from "../core/icons";

export function InlineCode({ children, className = "", ...props }: ComponentProps<"code">) {
  return (
    <code className={`inline-code ${className}`.trim()} {...props}>
      {children}
    </code>
  );
}

export function ChatLayout({
  className = "",
  density,
  composer,
  children,
}: {
  className?: string;
  density?: string;
  composer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`dotrix-chat-layout ${className}`.trim()} data-density={density}>
      {children}
      {composer}
    </div>
  );
}

export function ChatMessageList({ children, followKey }: { children: ReactNode; followKey?: unknown }) {
  return (
    <ChatScroller className="chat-scroll" followKey={followKey}>
      {children}
    </ChatScroller>
  );
}

export function ChatMessage({ sender = "assistant", className = "", children, ...props }: ComponentProps<"div"> & { sender?: string }) {
  const kind = sender === "user" ? "user" : "agent";
  return (
    <div className={`chat-msg ${kind} ${className}`.trim()} data-sender={sender} {...props}>
      {children}
    </div>
  );
}

export function ChatMessageBubble({ className = "", children, ...props }: ComponentProps<"div">) {
  return (
    <div className={`chat-bubble ${className}`.trim()} {...props}>
      {children}
    </div>
  );
}

type SelectorOption = { value: string; label: string };
type SelectorSection = { type: "section"; title?: string; options: SelectorOption[] } | SelectorOption[];

export function Selector({
  label,
  value,
  onChange,
  options,
  size,
}: {
  label: string;
  isLabelHidden?: boolean;
  value: string;
  onChange: (value: string) => void;
  options: SelectorSection[];
  hasSearch?: boolean;
  size?: string;
}) {
  const sections = options.map((section) => (Array.isArray(section) ? { title: undefined, options: section } : section));
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger size={size === "sm" ? "sm" : "default"} aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {sections.map((section, index) => (
          <SelectGroup key={section.title ?? index}>
            {section.title && <SelectLabel>{section.title}</SelectLabel>}
            {section.options.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}

export interface ComplexSelectorHandle {
  close: () => void;
}

type ComplexSelectorProps = {
  label: string;
  isLabelHidden?: boolean;
  value: string;
  placement?: string;
  alignment?: string;
  isDisabled?: boolean;
  onOpenChange?: (open: boolean) => void;
  handleRef?: Ref<ComplexSelectorHandle>;
  renderTrigger: (props: ComponentProps<"button"> & { role?: string }) => ReactNode;
  children: ReactNode | ((value: string, change: (value: string) => void, close: () => void) => ReactNode);
};

export function ComplexSelector({ label, value, isDisabled, onOpenChange, handleRef, renderTrigger, children }: ComplexSelectorProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const setOpenState = (next: boolean) => {
    setOpen(next);
    onOpenChange?.(next);
  };
  const close = () => setOpenState(false);
  useImperativeHandle(handleRef, () => ({ close }), [close]);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) close();
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <span ref={root} style={{ position: "relative", display: "inline-flex" }}>
      {renderTrigger({
        type: "button",
        role: "button",
        "aria-label": label,
        "aria-haspopup": "menu",
        "aria-expanded": open,
        disabled: isDisabled,
        onClick: () => {
          if (!isDisabled) setOpenState(!open);
        },
      })}
      {open && (
        <div
          className="pop floating"
          role="menu"
          aria-label={label}
          style={{ position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 70, minWidth: 200 }}
        >
          {typeof children === "function" ? children(value, () => undefined, close) : children}
        </div>
      )}
    </span>
  );
}

export function DesignButton({
  label,
  icon,
  isIconOnly,
  isDisabled,
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...props
}: ComponentProps<"button"> & {
  label: ReactNode;
  icon?: ReactNode;
  isIconOnly?: boolean;
  isDisabled?: boolean;
  variant?: "primary" | "secondary" | "ghost" | "destructive" | string;
  size?: "sm" | "md" | "lg" | string;
}) {
  const btnClass =
    variant === "primary" ? "btn btn-primary" : variant === "destructive" ? "btn btn-danger" : variant === "ghost" ? "btn btn-ghost" : "btn btn-secondary";
  const sizeClass = size === "sm" ? "btn-sm" : size === "lg" ? "btn-lg" : "";
  if (isIconOnly)
    return (
      <ActionButton
        {...props}
        type="button"
        className={[isDisabled ? "ibtn ibtn-sm" : "ibtn", className].filter(Boolean).join(" ")}
        aria-label={typeof label === "string" ? label : undefined}
        disabled={isDisabled}
      >
        {icon ?? children}
      </ActionButton>
    );
  return (
    <ActionButton {...props} type="button" className={[btnClass, sizeClass, className].filter(Boolean).join(" ")} disabled={isDisabled}>
      {icon}
      {label}
    </ActionButton>
  );
}

export interface ChatComposerInputHandle {
  focus: () => void;
}

export function ChatComposerInput({
  handleRef,
  value,
  onChange,
  placeholder,
  label,
  onKeyDown,
  isDisabled,
  status,
  pasteAsToken: _pasteAsToken,
  hasHistory: _hasHistory,
  onSubmit: _onSubmit,
  ...props
}: Omit<ComponentProps<"textarea">, "onChange" | "value"> & {
  handleRef?: Ref<ChatComposerInputHandle>;
  value: string;
  onChange: (value: string) => void;
  label?: string;
  isDisabled?: boolean;
  /** The PromptInput status model: "sending" makes the box read-only, "waiting" disables it. */
  status?: PromptStatus;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  pasteAsToken?: boolean;
  hasHistory?: boolean;
  onSubmit?: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(handleRef, () => ({ focus: () => ref.current?.focus() }), []);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);
  return (
    <span style={{ position: "relative", display: "block", minWidth: 0 }}>
      <textarea
        {...props}
        ref={ref}
        className={`composer-textarea ${props.className ?? ""}`.trim()}
        rows={1}
        value={value}
        disabled={isDisabled || status === "waiting"}
        readOnly={status === "sending"}
        placeholder={placeholder}
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
      />
    </span>
  );
}

export function ChatComposer({
  className = "",
  onSubmit,
  input,
  footerActions,
  sendActions,
  sendButton,
  children,
  value: _value,
  isDisabled: _isDisabled,
  isStopShown: _isStopShown,
  ...props
}: ComponentProps<"form"> & {
  value?: string;
  isDisabled?: boolean;
  isStopShown?: boolean;
  input?: ReactNode;
  footerActions?: ReactNode;
  sendActions?: ReactNode;
  sendButton?: ReactNode;
}) {
  return (
    <form
      {...props}
      className={className}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit?.(event);
      }}
    >
      <div>
        <div>{input}</div>
        <div>
          <div>{footerActions}</div>
          <div className="cmp-controls cmp-controls-right">
            {sendActions}
            {sendButton}
          </div>
        </div>
      </div>
      {children}
    </form>
  );
}

export function ChatSendButton({
  onSend,
  isDisabled,
  isStopShown,
  onStop,
  status,
  ...props
}: ComponentProps<"button"> & {
  onSend?: () => void;
  isDisabled?: boolean;
  isStopShown?: boolean;
  onStop?: () => void;
  /** The PromptInput status model: "working"/"stopping" turns the button into Stop (with `onStop`),
   *  "sending" spins, "waiting" disables. */
  status?: PromptStatus;
}) {
  const stoppable = isStopShown || Boolean(onStop);
  if (stoppable)
    return (
      <button
        {...props}
        type="button"
        className="kt-send kt-stop"
        disabled={isDisabled || status === "stopping"}
        onClick={onStop}
        aria-label={props["aria-label"] ?? "Stop"}
        data-tip="Stop this turn"
      >
        <Ic n="square" s={12} />
      </button>
    );
  const sending = status === "sending";
  const inactive = status !== undefined && status !== "ready";
  return (
    <button
      {...props}
      type="button"
      className="kt-send"
      disabled={isDisabled || inactive}
      onClick={onSend}
      aria-label={props["aria-label"] ?? "Send"}
      data-tip="Send"
    >
      {sending ? <Ic n="spinner-gap" s={15} cls="animate-spin" /> : <Ic n="arrow-up" s={15} />}
    </button>
  );
}

export function Lightbox({
  isOpen,
  onOpenChange,
  media,
  hasZoom: _hasZoom,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  media?: { src: string; alt?: string; caption?: string };
  hasZoom?: boolean;
}) {
  const [zoom, setZoom] = useState(false);
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, onOpenChange]);
  if (!isOpen || !media) return null;
  return (
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={media.caption ?? media.alt ?? "Image"}
      onClick={() => onOpenChange(false)}
      style={{ position: "fixed", inset: 0, zIndex: 100, display: "grid", placeItems: "center", background: "rgba(0,0,0,.72)", padding: 24 }}
    >
      <figure
        onClick={(event) => event.stopPropagation()}
        style={{ margin: 0, maxWidth: "min(1200px, 100%)", maxHeight: "100%", display: "flex", flexDirection: "column", gap: 8 }}
      >
        <img
          src={media.src}
          alt={media.alt ?? ""}
          style={{
            maxWidth: "100%",
            maxHeight: "82dvh",
            objectFit: "contain",
            transform: zoom ? "scale(1.6)" : undefined,
            transformOrigin: "center",
            transition: "transform .18s ease",
            cursor: zoom ? "zoom-out" : "zoom-in",
          }}
          onClick={() => setZoom((value) => !value)}
        />
        <figcaption className="faint" style={{ textAlign: "center", fontSize: 12 }}>
          {media.caption}
        </figcaption>
      </figure>
    </div>
  );
}
